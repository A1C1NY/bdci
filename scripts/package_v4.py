"""Create a self-contained competition candidate; do not invent external receipts."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.storage import read_json,write_json,write_text,digest,utc_now
from research_lab.framework import build_artifact_manifest,verify_artifact_manifest
from research_lab.model_config import load_models,get_key


def package():
    audit=read_json(ROOT/"research/v4/replay-audit.json")
    assert audit["valid"]
    assert (ROOT/"research/v4/reader-analysis.json").is_file()
    release=ROOT/"submissions/v4-candidate/能工智人"
    if release.exists():raise RuntimeError("Candidate exists; preserve it and use an explicit new release directory")
    code=release/"code";code.mkdir(parents=True)
    ignore=shutil.ignore_patterns("__pycache__","*.pyc",".git",".pytest_cache",".env.local","qa",".run.lock","*.log","*.aux","*.out","*.blg")
    for name in ("src","scripts","tests","config","integrations"):
        shutil.copytree(ROOT/name,code/name,ignore=ignore)
    # Keep legacy test fixtures and reproducibility generators with the code.
    shutil.copytree(ROOT/"experiments",code/"experiments",ignore=ignore)
    shutil.copytree(ROOT/"research/v4",code/"research/v4",ignore=ignore)
    shutil.copytree(ROOT/"references/templates",code/"references/templates",ignore=ignore)
    shutil.copytree(ROOT/"paper/v4",code/"paper/v4",ignore=ignore)
    for name in ("pyproject.toml","README.md",".env.example"):
        shutil.copyfile(ROOT/name,code/name)
    for folder in sorted((ROOT/"outputs").glob("v4-*")):
        shutil.copytree(folder,code/"outputs"/folder.name,ignore=ignore)
    for repository in ("jiuwenswarm","agent-core","stale"):
        archive_path=ROOT/".local/v4"/(repository+"-source.tar")
        subprocess.run(["git","-C",str(ROOT/"vendor"/repository),"archive","--format=tar","-o",str(archive_path),"HEAD"],check=True,
                       env={**os.environ,"GIT_LFS_SKIP_SMUDGE":"1"})
        target=code/"vendor"/repository;target.mkdir(parents=True)
        with tarfile.open(archive_path) as archive:archive.extractall(target,filter="data")
    upstream=read_json(ROOT/"integrations/jiuwenswarm/upstream_v4.json")
    for name in upstream["modified_files"]:
        shutil.copyfile(ROOT/"vendor/jiuwenswarm"/name,code/"vendor/jiuwenswarm"/name)
    write_text(code/"vendor/UPSTREAM_ASSETS.md","Pinned source snapshots are included. Unused upstream Git LFS media may be pointer files. The standalone SwarmFlow engine and tested helpers use no such media.\n")
    (release/"paper").mkdir();shutil.copyfile(ROOT/"paper/v4/paper.pdf",release/"paper/paper.pdf")
    (release/"docs").mkdir()
    for name in ("architecture.md","module_call.md","innovation.md"):
        shutil.copyfile(ROOT/"docs/v4"/name,release/"docs"/name)
    shutil.copyfile(ROOT/"docs/第四版运行说明.md",release/"docs/运行说明.md")
    for name in ("resource_report.md","resource_report.json","model_requests.json"):
        shutil.copyfile(ROOT/"research/v4"/name,release/name)
    shutil.copyfile(ROOT/"integrations/jiuwenswarm/PR_DESCRIPTION_V4.md",release/"framework_contribution.md")
    shutil.copyfile(ROOT/"integrations/jiuwenswarm/contribution_v4_with_tests.patch",release/"contribution_v4_with_tests.patch")
    (release/"AgenticReviewer").mkdir()
    write_text(release/"AgenticReviewer/README.md","新版 PDF 尚无对应的官方评审 Token。旧论文 Token 不适用，不能作为新稿凭证。\n")
    write_text(release/"提交说明.md","# 能工智人：第四版新研究\n\n英文论文、实际源码及原生工作流、公开数据及许可、原始模型记录、复现脚本、架构和资源报告均已包含。\n\n进入 code 后安装 `pip install -e .[research]`，执行 `python scripts/audit_v4.py` 可无 API 费用重放留出检索并核对读者上下文。`python scripts/analyze_readers_v4.py` 重新聚合已有模型评分，不发请求。真实模型阶段将产生 API 用量，仅在明确需要新实验时执行。\n\n当前是本地提交候选：新版 paper/paper.pdf 需要匹配的 AgenticReviewer Token；公开 PR 按用户要求自行提交。未代替用户向比赛网站提交。补齐凭证后压缩文件顶层仍应仅有“能工智人”目录。\n")
    status={"created_at":utc_now(),"team":"能工智人","paper_sha256":digest(release/"paper/paper.pdf"),
            "officially_submitted":False,"ready_for_official_submission":False,
            "blockers":["New PDF needs matching official AgenticReviewer Access Token","Public PR URL to be supplied by team owner"],"scientific_audit":audit}
    write_json(release/"submission_status.json",status)
    secrets={get_key(load_models(),a).encode() for a in ("deepseek","kimi")}
    files=[p for p in release.rglob("*") if p.is_file()]
    for p in files:
        content=p.read_bytes()
        if any(key in content for key in secrets) or re.search(rb"sk-[0-9a-f]{48,}",content):
            raise RuntimeError("Credential detected: "+str(p.relative_to(release)))
    manifest=build_artifact_manifest(release,files);write_json(release/"package_manifest.json",manifest)
    assert not verify_artifact_manifest(release,manifest)
    target=ROOT/"submissions/能工智人_v4_待新稿评审.zip"
    with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(release.rglob("*")):
            if path.is_file():archive.write(path,path.relative_to(release.parent))
    write_json(ROOT/"research/v4/package-status.json",{**status,"zip_path":str(target),"zip_sha256":digest(target),"zip_bytes":target.stat().st_size})
    print("Candidate package created",target.stat().st_size,"bytes",digest(target))


if __name__=="__main__":package()
