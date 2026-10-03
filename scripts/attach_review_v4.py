"""Attach verified new-PDF receipt and completion metadata without touching old releases."""
from pathlib import Path
import hashlib
import json
import re
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.storage import read_json,write_json,write_text,digest,utc_now
from research_lab.model_config import load_models,get_key

base=ROOT/"research/v4"
status=read_json(base/"package-status.json")
assert digest(ROOT/"paper/v4/paper.pdf")==status["paper_sha256"]
token=(ROOT/".local/AgenticReviewer-v4/PaperReview-AccessToken.txt").read_text("utf-8-sig").strip()
assert token and not token.startswith("sk-")
receipt={"destination":"https://paperreview.ai/","venue":"ICLR","email":"danny20051216@outlook.com",
    "submitted_at":utc_now(),"paper_sha256":status["paper_sha256"],"paper_pages":7,
    "submission_confirmed":True,"review_status":"pending","token_sha256":hashlib.sha256(token.encode()).hexdigest(),
    "proof":"reviewer-submission.png","authorization":"User explicitly approved this new PDF and email for this destination in the current conversation."}
write_json(base/"reviewer-submission.json",receipt)
status.update(official_review_submitted=True,official_review_status="pending",ready_for_official_submission=False,
    blockers=["Public PR URL to be supplied by team owner"],officially_submitted=False)
monitor=read_json(base/"monitor.json")
monitor["summary"]="第四版研究、7页论文与原始材料完成；新版已提交 ICLR 标准官方评审，Token 已取得，报告生成中。公开 PR 由团队自行提交。"
write_json(base/"monitor.json",monitor)
roadmap=read_json(ROOT/"research/progress.json")
roadmap.update(next_action="等待新稿官方评审；团队自行提交公开PR后补齐链接并进行比赛最终提交。",updated_at=utc_now())
roadmap["stages"][-1].update(status="awaiting_review",detail="新稿官方评审已提交且Token已保存；比赛尚未提交，PR待团队发布")
write_json(ROOT/"research/progress.json",roadmap)
check=read_json(base/"release-checks.json");check["official_review_new_pdf"]=True
write_json(base/"release-checks.json",check)
replacement={}
def add(name,path):replacement[name]=Path(path).read_bytes()
def put(name,value):replacement[name]=value.encode("utf-8")
for path in base.iterdir():
    if path.is_file() and path.name!="package-status.json":add("code/research/v4/"+path.name,path)
for path in (ROOT/"scripts").glob("*v4.py"):add("code/scripts/"+path.name,path)
for path in (ROOT/"outputs").glob("v4-*/state.json"):add("code/"+path.relative_to(ROOT).as_posix(),path)
for name in ("resource_report.md","resource_report.json","model_requests.json"):add(name,base/name)
add("docs/reviewer-submission.png",base/"reviewer-submission.png")
add("docs/监督审查.md",base/"supervisor-review.md")
add("code/research/progress.json",ROOT/"research/progress.json")
put("AgenticReviewer/PaperReview-AccessToken.txt",token+"\n")
put("AgenticReviewer/README.md","新版论文已成功提交 paperreview.ai，选择 ICLR 标准。Token 仅对应同包 paper/paper.pdf；报告仍在生成，不能声称已取得评分。提交回执与 SHA 见 reviewer-submission.json。\n")
put("AgenticReviewer/reviewer-submission.json",json.dumps(receipt,ensure_ascii=False,indent=2))
embedded_status={key:value for key,value in status.items() if key not in {"zip_path","zip_sha256","zip_bytes"}}
put("submission_status.json",json.dumps(embedded_status,ensure_ascii=False,indent=2))
put("提交说明.md","# 能工智人：第四版交接包\n\n新版7页英文ICLR格式论文已送 paperreview.ai 并获得匹配的新Token，报告仍在生成。包括完整源码、固定上游、公开数据许可、实际原始模型记录、复现、资源及贡献补丁。公开PR依用户要求由团队自行提交；比赛网站尚未提交。\n\n离线复核：在code目录安装 `pip install -e .[research]`，然后 `python scripts/audit_v4.py` 和 `python scripts/analyze_readers_v4.py`，均不发API请求。公开包不携带密钥或全项目私有账本；继续付费研究请用原工作区，迁移前需另行迁移全局账本以继承预算。\n\n补齐公开PR链接后，最终压缩包按官网要求命名，顶层仍只有“能工智人”。\n")
source=ROOT/"submissions/能工智人_v4_待新稿评审.zip"
target=ROOT/"submissions/能工智人_v4_已送评_待PR.zip"
assert source.resolve()!=target.resolve()
prefix="能工智人/"
with zipfile.ZipFile(source) as old:
    manifest=json.loads(old.read(prefix+"package_manifest.json"))
    entries={r["path"]:r for r in manifest["artifacts"]}
    for name,content in replacement.items():entries[name]={"path":name,"bytes":len(content),"sha256":hashlib.sha256(content).hexdigest()}
    manifest["artifacts"]=[entries[k] for k in sorted(entries)]
    put("package_manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2))
    secrets={get_key(load_models(),a).encode() for a in ("deepseek","kimi")}
    with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as new:
        for item in old.infolist():
            name=item.filename.removeprefix(prefix)
            if name in replacement:continue
            new.writestr(item,old.read(item.filename))
        for name,content in replacement.items():
            assert not any(key in content for key in secrets) and not re.search(rb"sk-[0-9a-f]{48,}",content),name
            new.writestr(prefix+name,content)
status.update(zip_path=str(target),zip_sha256=digest(target),zip_bytes=target.stat().st_size)
write_json(base/"package-status.json",status)
print("New-paper receipt attached; public PR pending.",target.stat().st_size,digest(target))
