"""Chạy evals/run_evals.py của lab, không sửa providers.py, với 2 điều chỉnh request trong process này:
- timeout HTTP >= LONG_TIMEOUT (mặc định 180s) cho model chậm;
- REASONING_EFFORT=none: thêm reasoning_effort vào request của model có tên chứa 'luna'
  (gpt-5.6-luna chỉ cho dùng function tools trên /v1/chat/completions khi reasoning_effort='none').

Tái lập eval_bonus.json (code agent giữ nguyên):
  PROVIDER=openai OPENAI_API_KEY=... REASONING_EFFORT=none python3 eval_runs/run_evals_wrapper.py --bonus \
      --model gpt-5.6-luna --judge-provider openai --judge-model gpt-4o-mini --output eval_bonus.json
"""
import os
import sys
import urllib.request
from pathlib import Path

LONG_TIMEOUT = float(os.getenv('LONG_TIMEOUT', '180'))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'evals'))

_orig = urllib.request.urlopen


def _urlopen(req, data=None, timeout=None, *args, **kwargs):
    return _orig(req, data, max(timeout or 0, LONG_TIMEOUT), *args, **kwargs)


urllib.request.urlopen = _urlopen  # providers.py gọi urllib.request.urlopen(req, timeout=60)

# REASONING_EFFORT=none: chèn reasoning_effort vào request OpenAI-compatible (vd. model *-luna chỉ cho dùng
# function tools trên /v1/chat/completions khi reasoning_effort='none'). Chỉ áp cho model agent (MODEL_FILTER).
import providers  # noqa: E402

EFFORT = os.getenv('REASONING_EFFORT')
MODEL_FILTER = os.getenv('EFFORT_MODEL_FILTER', 'luna')
if EFFORT:
    _post = providers.post_json

    def _post_json(url, headers, payload):
        if isinstance(payload, dict) and MODEL_FILTER in str(payload.get('model', '')):
            payload = {**payload, 'reasoning_effort': EFFORT}
        return _post(url, headers, payload)

    providers.post_json = _post_json

import run_evals  # noqa: E402

if __name__ == '__main__':
    sys.argv = ['run_evals.py'] + sys.argv[1:]
    run_evals.main()
