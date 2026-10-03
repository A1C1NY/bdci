"""Export study-only measured gateway usage and explicit unmeasured boundaries."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.storage import read_json,write_json,write_text,utc_now
from research_lab.model_config import load_models
from research_lab.token_ledger import TokenLedger


def report():
    config=load_models();ledger=read_json(Path(config["ledger_directory"])/"ledger.json")
    requests=[r for r in ledger["requests"] if r["purpose"].startswith("v4:")]
    snapshot=TokenLedger(config).snapshot()
    measured={a:sum(r["usage"]["total_tokens"] for r in requests if r["alias"]==a and r.get("usage")) for a in config["models"]}
    unknown={a:sum(r["reserved_tokens"] for r in requests if r["alias"]==a and not r.get("usage")) for a in config["models"]}
    stages={}
    for folder in sorted((ROOT/"outputs").glob("v4-*")):
        if (folder/"state.json").exists():
            stages[folder.name]=read_json(folder/"state.json")
    result={"generated_at":utc_now(),"study":"v4 external STALE audit","requests":len(requests),
        "reported_tokens":measured,"unsettled_reservations":unknown,"account_snapshot":snapshot["models"],
        "stage_states":stages,"deterministic_replay":read_json(ROOT/"research/v4/replay-audit.json"),
        "limits":["Gateway aliases are not independent authentication of model weights/version.",
                  "Codex supervisor, browser and web-search service usage is not measured by this ledger.",
                  "No monetary price supplied; no invented cost estimate.",
                  "Unknown usage remains a reservation, not zero tokens or measured consumption.",
                  "CPU replay wall time is measured; original retrieval elapsed time was not instrumented.",
                  "Concurrency cap is per workflow, not a gateway-wide scheduler."]}
    write_json(ROOT/"research/v4/resource_report.json",result)
    write_json(ROOT/"research/v4/model_requests.json",{"scope":"v4 only, no credentials","requests":requests})
    text="# 第四版资源报告\n\n"
    text+=f"本轮网关请求 {len(requests)} 次；DeepSeek 已报告 {measured['deepseek']:,} Token，Kimi 已报告 {measured['kimi']:,} Token。\n\n"
    text+="| 模型 | 本轮已报告 | 本轮未知预留 | 全项目已报告 | 上限 |\n|---|---:|---:|---:|---:|\n"
    for a in measured:text+=f"| {a} | {measured[a]} | {unknown[a]} | {snapshot['models'][a]['reported_tokens']} | {snapshot['models'][a]['limit']} |\n"
    text+="\n原始请求、失败、重试性质和逐阶段记录见 model_requests.json。未知预留不能视为实际消耗。独立完整检索重放耗时 "+str(round(result['deterministic_replay']['wall_seconds'],2))+" 秒。\n\n"
    text+="未计量 Codex 主监督者服务 Token、浏览器和联网检索成本；没有提供货币单价，不生成虚构费用。原检索运行没有计时仪表，因此仅报告实际测量的重放耗时。并发上限每个工作流为 3，不等于全网关最多 3。\n"
    write_text(ROOT/"research/v4/resource_report.md",text)
    print({"requests":len(requests),"reported_tokens":measured,"unknown_reservations":unknown})


if __name__=="__main__":report()
