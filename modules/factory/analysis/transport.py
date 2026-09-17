"""Resolve registered media at the analysis boundary, preserving durable receipts."""
import hashlib
from pathlib import Path
from ..providers.synchronous import SynchronousAdapter
from ..testing.fakes import ProviderError
from .analyzer import parse_analysis


class ArtifactAnalyzer(SynchronousAdapter):
    def __init__(self, state_dir, artifacts, analyze_media):
        super().__init__(state_dir)
        self.artifacts, self.analyze_media = artifacts, analyze_media

    def execute(self, request):
        artifact_id = request.get("artifact_id")
        row = self.artifacts.db.uow().artifacts.get(artifact_id)
        if not row or row["kind"] != "video" or row["sha256"] != request["artifact_sha256"]:
            raise ProviderError("analysis_media_mismatch")
        path = self.artifacts.path_for(artifact_id)
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != row["sha256"]:
            raise ProviderError("analysis_media_changed")
        result = self.analyze_media(path, request)
        parse_analysis(result)
        return result, None, {}
