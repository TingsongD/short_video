import json
import subprocess
import sys


def test_helper_refuses_unversioned_input_before_opening_files(tmp_path):
    request = tmp_path/'request.json'
    request.write_text(json.dumps({'database': '/must-not-open.db'}))
    result = subprocess.run([sys.executable, '-m', 'modules.factory.analysis.local_helper', str(request)],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)['error'] == 'invalid_helper_request'
