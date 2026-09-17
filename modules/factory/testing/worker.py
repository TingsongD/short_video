"""Isolated offline fault-test worker; accepts only pytest/temporary workspaces."""
from pathlib import Path
import sys,tempfile
from ..bootstrap import bootstrap
from ..services.worker import ApplicationWorker
from .durable import CrashDrive,DiskGeneration,configure_faults
root=Path(sys.argv[1]).resolve()
if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) and not root.is_relative_to(Path('/tmp').resolve()):
    raise SystemExit('Temporary fixture root required')
s=bootstrap(root,providers={'jimeng_canvas':DiskGeneration(root),'google_vertex':DiskGeneration(root,'google_vertex')},drive=CrashDrive(root),settings={'mode':'offline','drive_folder_id':'folder'})
s.scheduler.lease_s=1
configure_faults(s,root)
ApplicationWorker(s).run()
