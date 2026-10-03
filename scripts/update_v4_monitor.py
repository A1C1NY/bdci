"""Project durable evidence into the existing read-only dashboard."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.storage import read_json,write_json,utc_now
base=ROOT/"research/v4"
frozen=read_json(base/"frozen.json")
monitor=read_json(base/"monitor.json")
monitor["decisions"]=[monitor["decisions"][0]]+frozen["decisions"]
monitor["summary"]="两个候选已完成开发评价，保留轻量变更提示，淘汰高时间权重；正式留出及双模型读者实验进行中。"
write_json(base/"monitor.json",monitor)
write_json(ROOT/"research/progress.json",{"title":"有限上下文中的更新证据丢失","question":"更新证据能否被检索到，检索收益能否转化为模型回答收益？", "status":"evaluating_holdout","updated_at":utc_now(),"team":"能工智人","owner":"Codex 主监督者","next_action":"完成冻结留出和读者实验，随后证据绑定写作、审查和新提交包。","note":"旧论文与评审凭证保留。第四版使用原生 SwarmFlow、公开 STALE 数据和两次可追溯开发迭代；新稿不沿用旧评审 Token。","stages":[{"id":k,"label":label,"status":status,"detail":detail} for k,label,status,detail in [("framework","原生工作流","completed","真实调用与阶段恢复验证通过"),("novelty","文献与立项","completed","淘汰重命名创新主张，保留外部证据审计"),("development","开发迭代","completed","两次候选，一次保留一次淘汰"),("evaluation","独立评价","in_progress","320 场景留出；24 场景双模型读者"),("paper","论文与审查","pending","证据绑定生成，保留负面结果"),("release","比赛交付","pending","新 PDF、源码、复现、资源、贡献补丁")]]})
