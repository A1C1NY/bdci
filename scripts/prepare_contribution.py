"""Prepare a source-only contribution patch, with tests in upstream layout."""
import ast
import difflib
from pathlib import Path
import sys
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from research_lab.storage import write_text

tests = (ROOT / 'tests/test_framework_artifacts.py').read_text(encoding='utf-8')
campaign = (ROOT / 'tests/test_campaign.py').read_text(encoding='utf-8')
node = next(n for n in ast.parse(campaign).body if isinstance(n, ast.FunctionDef) and n.name == 'test_budget_reservations_are_pure_and_bounded')
tests += '\n\nfrom copy import deepcopy\nfrom jiuwenswarm.common.research_budget import BudgetExceeded, reserve_research_attempt\n\n'
tests += ast.get_source_segment(campaign, node) + '\n'
name = 'tests/unit_tests/common/test_research_artifacts.py'
write_text(ROOT / 'integrations/jiuwenswarm/pr_files' / name, tests)
patch = (ROOT / 'integrations/jiuwenswarm/framework.patch').read_text(encoding='utf-8')
patch += f'diff --git a/{name} b/{name}\nnew file mode 100644\n'
patch += ''.join(difflib.unified_diff([], tests.splitlines(keepends=True), fromfile='/dev/null', tofile='b/' + name))
write_text(ROOT / 'integrations/jiuwenswarm/contribution_with_tests.patch', patch)
check = Path(tempfile.mkdtemp(prefix='contribution-check-', dir=ROOT / '.local'))
subprocess.run(['git', 'init', '--quiet', str(check)], check=True)
original = subprocess.run(['git', '-C', str(ROOT / 'vendor/jiuwenswarm'), 'show',
                           'ce8af2051fd7c5dff85a09f8185fce64d32893a6:jiuwenswarm/common/team_artifacts.py'],
                          check=True, capture_output=True).stdout
baseline = check / 'jiuwenswarm/common/team_artifacts.py'
baseline.parent.mkdir(parents=True)
baseline.write_bytes(original)
subprocess.run(['git', '-C', str(check), 'apply', '--check',
                str(ROOT / 'integrations/jiuwenswarm/contribution_with_tests.patch')], check=True)
print('Prepared source-only patch with 2 implementation files and 1 upstream-layout test file.')
