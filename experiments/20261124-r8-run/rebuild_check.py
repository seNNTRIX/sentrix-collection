"""RE2-OB rebuild check in this environment (criteria of experiments/20261123-re2ob-v2-rebuild-check):
same selected hyperparameters as frozen.json, inner LOSO Avg@5 and inner repetition-CV AUROC equal to 3 decimals."""
import json, sys
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from training import run_r6 as r6
fz = json.loads((ROOT/'experiments/20261028-re2ob-v2-freeze/frozen.json').read_text())
R = pd.read_parquet(ROOT/'data/features/re2ob-v0/ranking.parquet'); D = pd.read_parquet(ROOT/'data/features/re2ob-v0/detection.parquet')
rel = r6.rank_fsets(R)['rel']; dcols = r6.det_fsets(D, R)['all']
assert rel == fz['ranking']['features'] and dcols == fz['detection']['features']
rp, ri = r6.select(R, rel, sorted(R['meta_root_cause'].unique()), 'meta_root_cause', r6.RANK_GRIDS['rf'], lambda d,c,p: r6.fit_rank('rf',d,c,p), r6.rank_avg5)
dp, di = r6.select(D, dcols, sorted(D['meta_fold'].unique()), 'meta_fold', r6.DET_GRIDS['lgbm'], lambda d,c,p: r6.fit_det('lgbm',d,c,p), r6.det_auroc)
fr = {k: fz['ranking']['params'][k] for k in rp}; fd = {k: fz['detection']['params'][k] for k in dp}
out = {'ranking_params': rp, 'frozen_ranking_params': fr, 'inner_loso_avg5': ri, 'frozen_inner_loso_avg5': fz['ranking']['inner_loso_avg5'],
       'detection_params': dp, 'frozen_detection_params': fd, 'inner_rep_auroc': di, 'frozen_inner_rep_auroc': fz['detection']['inner_rep_cv_auroc']}
out['pass'] = rp == fr and dp == fd and round(ri,3) == round(out['frozen_inner_loso_avg5'],3) and round(di,3) == round(out['frozen_inner_rep_auroc'],3)
(Path(__file__).parent/'rebuild-check.json').write_text(json.dumps(out, indent=1)); print(json.dumps(out, indent=1))
