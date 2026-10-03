"""Report missingness, paired-complete scenario contrasts and evidence association."""
from collections import Counter, defaultdict
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from research_lab.storage import read_json,write_json
BASE=ROOT/"research/v4"


def analyze():
    protocol=read_json(BASE/"frozen.json")
    answers=read_json(ROOT/"outputs/v4-readers/results.json")
    judgments=read_json(ROOT/"outputs/v4-judges/results.json")
    manifest=read_json(BASE/"reader-manifest.json")
    judge_manifest=read_json(BASE/"judge-manifest.json")
    rows=[]
    for item in manifest:
        answer=answers.get(item["id"])
        key=f"{item['uid']}:{item['policy']}:{item['model']}"
        grade=judgments.get(key)
        dim=item["dim"].replace("_query","_eval")
        valid=isinstance(grade,dict) and dim in grade
        rows.append({**item,"reader_completed":isinstance(answer,dict) and "answer" in answer,
                     "judge_completed":valid,"passed":grade[dim]["pass"] if valid else None,
                     "judge_reasoning":grade[dim]["reasoning"] if valid else None})
    write_json(BASE/"reader-scored-rows.json",rows)
    aggregates=[];paired=[];table=[];associations=[]
    for model in protocol["reader_models"]:
        for policy in protocol["reader_policies"]:
            subset=[r for r in rows if r["model"]==model and r["policy"]==policy]
            judged=[r for r in subset if r["judge_completed"]]
            passes=sum(r["passed"] for r in judged)
            aggregates.append({"model":model,"policy":policy,"attempted":len(subset),
                "completed":sum(r["reader_completed"] for r in subset),"judged":len(judged),"passes":passes,
                "pass_rate_observed":passes/len(judged) if judged else None,
                "all_attempts_lower_bound":passes/len(subset),
                "all_attempts_upper_bound":(passes+len(subset)-len(judged))/len(subset)})
            table.append([model,"BM25" if policy=="bm25" else "+time+cue",
                f"{sum(r['reader_completed'] for r in subset)}/{len(subset)}",f"{passes}/{len(judged)}",
                f"{100*passes/len(judged):.1f}" if judged else "--"])
            for present in (False,True):
                obs=[r for r in judged if r["new_present"]==present]
                associations.append({"model":model,"policy":policy,"verbatim_new_present":present,
                    "n":len(obs),"passes":sum(r["passed"] for r in obs)})
        dif=[];uids=[]
        for uid in protocol["reader_uids"]:
            groups=[[r for r in rows if r["model"]==model and r["policy"]==p and r["uid"]==uid and r["judge_completed"]] for p in protocol["reader_policies"]]
            if all(len(g)==3 for g in groups):
                dif.append(np.mean([r["passed"] for r in groups[1]])-np.mean([r["passed"] for r in groups[0]]));uids.append(uid)
        values=np.array(dif)
        if len(values):
            rng=np.random.default_rng(20260929)
            boot=np.mean(values[rng.integers(0,len(values),(10000,len(values)))],axis=1)
            paired.append({"model":model,"n_complete_scenarios":len(values),"uids":uids,"delta":float(values.mean()),"ci95":[float(x) for x in np.quantile(boot,[.025,.975])]})
    completed=sum(r["reader_completed"] for r in rows)
    graded=sum(r["judge_completed"] for r in rows)
    narrative=f"Of {len(rows)} planned reader requests, {completed} returned valid answers; {len(rows)-completed} were missing or invalid. Opposite-model judging produced grades for {graded} answers. "
    narrative+=" ".join(f"On {p['n_complete_scenarios']} complete paired scenarios, {p['model']} showed a judged-pass difference of {100*p['delta']:+.2f} percentage points (95% scenario-bootstrap interval {100*p['ci95'][0]:+.2f} to {100*p['ci95'][1]:+.2f})." for p in paired)
    result={"attempted":len(rows),"reader_completed":completed,"reader_missing":len(rows)-completed,
        "judge_requests":len(judgments),"judge_missing":sum(not isinstance(r,dict) or "dim1_eval" not in r for r in judgments.values()),
        "graded_answers":graded,"aggregates":aggregates,"paired_complete":paired,"evidence_association":associations,
        "narrative":narrative,
        "interpretation":"These are exploratory opposite-model judgments, not human accuracy labels. Complete-case estimates may be biased by missing requests. Missing outcomes are also bounded pessimistically and optimistically in the released analysis. Verbatim evidence presence is an observational diagnostic, not randomized exposure; paraphrased update evidence may remain when exact containment is false. Neither a non-significant difference nor an apparent gain establishes a general reader benefit. The same judge route is used within each reader comparison, but different readers have different judges and should not be ranked against one another.",
        "table":{"caption":"Reader pilot at 4096 bytes. Valid counts are completed reader requests; passes/graded excludes missing reader or judge groups. Percentages are descriptive. Each reader is graded by the opposite model.","headers":["Reader","Selector","Valid","Pass/graded","Pass %"],"rows":table}}
    write_json(BASE/"reader-analysis.json",result)
    print(narrative)


if __name__=="__main__":analyze()
