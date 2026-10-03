"""Prepare named review bundle, without credentials or a fabricated reviewer token."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from research_lab.storage import read_json,write_json,write_text,digest,utc_now
from research_lab.model_config import load_models,get_key
from research_lab.token_ledger import TokenLedger
from research_lab.framework import build_artifact_manifest,verify_artifact_manifest


def prepare():
    audit=read_json(ROOT/'research/memory_v3/release_audit.json')
    if not audit['valid']: raise ValueError('Scientific artifact audit failed')
    for name,decision,applied in [('deepseek-source-discussion-001','accepted_checked_prose',True),('kimi-source-final-audit-001','partially_accepted',False)]:
        p=ROOT/f'outputs/{name}/state.json';state=read_json(p)
        state.update(status='supervisor_reviewed',supervisor_decision=decision,applied_to_research=applied)
        write_json(p,state)
    config=load_models();snapshot=TokenLedger(config).snapshot()
    write_json(ROOT/'research/memory_v3/usage_release_snapshot.json',snapshot)
    ledger=read_json(Path(config['ledger_directory'])/'ledger.json')
    purposes={'memory_case_design_001','source_protocol_audit_001','source_results_discussion_001','source_final_evidence_audit_001'}
    study=[r for r in ledger['requests'] if r['purpose'] in purposes or r['purpose'].startswith('source-reader:')]
    amounts={a:sum(r['usage']['total_tokens'] for r in study if r['alias']==a and r.get('usage')) for a in config['models']}
    resources={'generated_at':utc_now(),'scope':'source-memory study only; supervisor Codex tokens not observable',
        'study_requests':len(study),'study_reported_tokens':amounts,'study_unknown_requests':sum(r.get('usage') is None for r in study),
        'reader_pilot':read_json(ROOT/'outputs/source-reader-pilot/resource_report.json'),
        'cpu_experiment_jobs':483,'cpu_experiment_wall_seconds_sum':read_json(ROOT/'research/memory_v3/results/analysis.json')['cpu_job_wall_seconds_sum'],
        'audit_wall_seconds':audit['audit_wall_seconds'],'account_snapshot':snapshot['models'],'billing_cost':None}
    write_json(ROOT/'research/memory_v3/resource_report.json',resources)
    lines=['# 资源报告','',f"- 正式研究模型请求：{len(study)}；DeepSeek {amounts['deepseek']:,}、Kimi {amounts['kimi']:,} 已报告Token。",
        '- 72次模型读取试验及4次本轮有限设计/撰写/审核任务全部计入。',
        f"- CPU实验483次，执行器进程墙钟时间合计{resources['cpu_experiment_wall_seconds_sum']:.3f}秒；并行执行，不能当作总实际等待时间。",
        f"- 离线完整重放额外耗时{audit['audit_wall_seconds']:.3f}秒，已单独列出。",
        '- 模型读取2次截断记错且未选择性重试；思考Token属于输出子集，不重复相加。',
        '- 账本包含此前接口排查成本；历史请求无usage时保留预留，不能声称零消耗。',
        '- Codex主监督者自身的服务Token、联网检索和工具调用费用未由本地API账本计量；不是端到端总成本。',
        '- 网关未给出货币价格，因此不虚构费用；模型别名不等于独立验证的权重身份。','',
        '| 模型 | 首阶段上限 | 全项目已报告 | 全项目未结算预留 | 剩余可准入 |','|---|---:|---:|---:|---:|']
    for a,r in snapshot['models'].items():lines.append(f"| {a} | {r['limit']} | {r['reported_tokens']} | {r['held_tokens']} | {r['remaining_admissible_tokens']} |")
    write_text(ROOT/'docs/release/resource_report.md','\n'.join(lines)+'\n')
    release=ROOT/'submissions/review-ready-v2/能工智人'
    release.mkdir(parents=True,exist_ok=False)
    code=release/'code';code.mkdir()
    ignored=shutil.ignore_patterns('__pycache__','*.pyc','.git','.local','.env.local','.test-tmp*','.pytest_cache','qa')
    for name in ('src','scripts','tests','experiments','config','research','integrations','docs'):
        shutil.copytree(ROOT/name,code/name,ignore=ignored)
    shutil.copytree(ROOT/'references/templates',code/'references/templates',ignore=ignored)
    shutil.copytree(ROOT/'paper',code/'paper',ignore=shutil.ignore_patterns('qa','*.log','*.aux','*.out','*.blg'))
    for name in ('pyproject.toml','.env.example','README.md'):
        shutil.copyfile(ROOT/name,code/name)
    # Include only this study and its actual model-worker provenance, not unrelated user data.
    output_names=[f'source-{s}-b{b}' for s in ('dev','holdout','stress') for b in (384,768,1536)]
    output_names+=['source-reader-pilot','deepseek-memory-cases-001','kimi-source-protocol-audit-001','deepseek-source-discussion-001','kimi-source-final-audit-001']
    for name in output_names:shutil.copytree(ROOT/'outputs'/name,code/'outputs'/name,ignore=ignored)
    # Full pinned upstream source archive with the actual reviewed modifications overlaid.
    temp=ROOT/'.local/upstream-source-release.tar'
    subprocess.run(['git','-C',str(ROOT/'vendor/jiuwenswarm'),'archive','--format=tar','-o',str(temp),'HEAD'],check=True,env={**os.environ,'GIT_LFS_SKIP_SMUDGE':'1'})
    vendor=code/'vendor/jiuwenswarm';vendor.mkdir(parents=True)
    with tarfile.open(temp) as archive:archive.extractall(vendor,filter='data')
    write_text(code/'vendor/UPSTREAM_ASSETS.md','Pinned upstream Git source is included. Git LFS assets remain pointer files: the upstream demonstration video download returned HTTP 404. These assets are not used by this study or its offline reproduction.\n')
    for name in read_json(ROOT/'integrations/jiuwenswarm/upstream.json')['modified_files']:
        shutil.copyfile(ROOT/'vendor/jiuwenswarm'/name,vendor/name)
    # Reproduction and contribution material in the exact official top-level locations.
    (release/'paper').mkdir();shutil.copyfile(ROOT/'paper/paper.pdf',release/'paper/paper.pdf')
    (release/'docs').mkdir()
    for name in ('architecture.md','module_call.md','innovation.md'):shutil.copyfile(ROOT/'docs/release'/name,release/'docs'/name)
    shutil.copyfile(ROOT/'docs/release/resource_report.md',release/'resource_report.md')
    contribution=(ROOT/'integrations/jiuwenswarm/framework_contribution.md').read_text(encoding='utf-8')
    contribution+='\n\n## 本轮实际使用与验证\n483个CPU任务和72个模型读取记录使用真实JiuwenSwarm产物清单扩展。37项相关测试通过，57,960条CPU预测在新进程完整重放一致。持久Token账本由research_lab实现，不能把该能力归到原始上游预算模块。随包patch可应用于指定commit；尚无公开PR链接。\n'
    write_text(release/'framework_contribution.md',contribution)
    (release/'AgenticReviewer').mkdir()
    write_text(release/'AgenticReviewer/README.md','# 等待官方评审\n\n尚无Access Token。不得把此文件当作评审凭证。得到与paper/paper.pdf同一SHA-256版本对应的真实Token后，再创建PaperReview-AccessToken.txt。\n')
    write_json(release/'resource_report.json',resources)
    write_json(release/'model_requests.json',{'requests':study,'scope':'Only study requests; no API keys or raw credentials.'})
    write_text(release/'提交说明.md','# 能工智人：待官方评审版本\n\n包含英文ICLR论文、完整研究代码、固定上游源码与补丁、实际实验和模型响应、资源及技术文档。先在code目录执行scripts/audit_source_release.py进行无API复核。\n\n**当前不可当作最终提交：缺少与最终论文对应的AgenticReviewer Access Token；公开PR链接尚无，patch已提供。** 正式上传需完成这些外部环节的确认。\n\n论文SHA-256：'+digest(release/'paper/paper.pdf')+'\n')
    blocked=['Missing official AgenticReviewer Access Token','No public PR URL; patch provided, contribution acceptance depends on organizer']
    status={'team':'能工智人','prepared_at':utc_now(),'paper_sha256':digest(release/'paper/paper.pdf'),'officially_submitted':False,
        'ready_for_official_submission':False,'blockers':blocked,'audit':audit}
    write_json(release/'submission_status.json',status)
    # Exact active secrets and generic real-key shapes must never enter the package.
    secrets={get_key(config,a).encode() for a in config['models']}
    for path in release.rglob('*'):
        if not path.is_file():continue
        data=path.read_bytes()
        if any(key in data for key in secrets) or re.search(rb'sk-[0-9a-f]{48,}',data):
            raise RuntimeError('Credential pattern detected in package file: '+path.relative_to(release).as_posix())
    files=[p for p in release.rglob('*') if p.is_file()]
    manifest=build_artifact_manifest(release,files)
    write_json(release/'package_manifest.json',manifest)
    if verify_artifact_manifest(release,manifest):raise RuntimeError('Package hash audit failed')
    zip_path=ROOT/'submissions/能工智人_待评审.zip'
    if zip_path.exists():raise RuntimeError('Never overwrite a release ZIP')
    with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p in release.rglob('*'):
            if p.is_file():archive.write(p,Path('能工智人')/p.relative_to(release))
    write_json(ROOT/'research/memory_v3/package_status.json',{**status,'zip':zip_path.name,'zip_sha256':digest(zip_path),'bytes':zip_path.stat().st_size})
    print(json.dumps({'package':str(zip_path),'bytes':zip_path.stat().st_size,'study_tokens':amounts,'blockers':blocked},ensure_ascii=False))


if __name__=='__main__':prepare()
