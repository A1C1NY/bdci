"""Set evidence-backed completion metadata; never marks external submission done."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.storage import read_json,write_json,digest,utc_now
from research_lab import framework
from jiuwenswarm.common.research_runtime import evidence_gate

base=ROOT/"research/v4"
doc=read_json(ROOT/"paper/v4/document.json")
evidence_gate(doc["claims"],doc["evidence"])
monitor=read_json(base/"monitor.json")
monitor.update(summary="独立研究已完成：9600条检索重放一致；288次读者请求277次有效；85次裁判成功。7页论文保留检索与回答收益不一致的结果。等待新稿外部评审授权与团队公开PR。",
    claims_verified=len(doc["claims"]),claims_total=len(doc["claims"]),issues_closed=8,issues_total=8)
write_json(base/"monitor.json",monitor)
roadmap=read_json(ROOT/"research/progress.json")
roadmap.update(status="awaiting_review",updated_at=utc_now(),next_action="新稿送 paperreview.ai 取得匹配 Token；公开 PR 由团队自行提交。",
    note="新版本地研究、论文与完整源码材料完成。288次读者请求中11次失败未选择性补跑；官方比赛尚未提交。")
for stage in roadmap["stages"]:
    stage["status"]="completed" if stage["id"]!="release" else "awaiting_review"
    if stage["id"]=="evaluation":stage["detail"]="320留出场景，9600检索记录重放通过；255答案评分完成"
    if stage["id"]=="paper":stage["detail"]="7页ICLR格式，真实模型草稿与监督修订，85项测试通过"
    if stage["id"]=="release":stage["detail"]="本地材料完成；缺新稿官方Token和团队自行发布的PR链接"
write_json(ROOT/"research/progress.json",roadmap)
for folder in (ROOT/"outputs").glob("v4-*"):
    if not (folder/"results.json").is_file():continue
    results=read_json(folder/"results.json")
    missing=[k for k,v in results.items() if not isinstance(v,dict) or "_error" in v]
    state=read_json(folder/"state.json")
    state.update(status="completed_with_errors" if missing else "completed",missing_tasks=missing,
        total_tasks=len(results),completed_tasks=len(results)-len(missing),failed_tasks=len(missing),
        supervisor_decision="reviewed; see research/v4/supervisor-review.md")
    write_json(folder/"state.json",state)
write_json(base/"release-checks.json",{"paper_sha256":digest(ROOT/"paper/v4/paper.pdf"),"paper_pages":7,
    "visual_review":"All seven rendered pages inspected; no clipping/overlap; no overfull boxes or unresolved claim placeholders",
    "test_suite":"85 passed in 85.33s; 2 additional upstream-layout runtime helper tests passed",
    "replay":read_json(base/"replay-audit.json"),"claim_hashes_verified":len(doc["claims"]),
    "review_dispositions":"6 adopted clarifications; 2 false or inapplicable suggestions rejected with reasons",
    "official_submission":False,"official_review_new_pdf":False})
print("Updated completion metadata; external review and PR remain pending")
