#!/usr/bin/env python3
"""Stage G metadata validator reusing the unchanged D.6 parser."""
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('stage_e_metadata_base', Path(__file__).parents[1] / 'stage-d/validate_release_metadata.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
base.VERSIONS = {**base.VERSIONS, 'stage': 'G', 'phase': 'G',
                 'config_schema_version': '4', 'migration_version': 'wvc-domain-v1',
                 'platform_api_contract_version': '1'}
validate = base.validate

if __name__ == '__main__':
    try:
        validate(Path(sys.argv[1]))
    except Exception:
        raise SystemExit('FAIL: Stage G metadata') from None
    print('Stage G metadata: PASS')
