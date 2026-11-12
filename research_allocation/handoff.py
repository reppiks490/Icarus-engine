"""Evidence package for owner review. Does not mutate or import the runtime."""
from .contracts import digest, text, utc
from .decision import evaluate, flags


def prepare_handoff(raw, *, owner, as_of, source_revision):
    text(owner, 'owner'); utc(as_of)
    if (not isinstance(source_revision, str) or len(source_revision) != 40
            or any(c not in '0123456789abcdef' for c in source_revision)):
        raise ValueError('source_revision must be an exact lowercase Git SHA')
    analysis = evaluate(raw)
    body = {'schema_version': 'atlas.owner_handoff.v1', 'owner': owner, 'as_of': as_of,
            'atlas_source_revision': source_revision, 'model_hash': analysis['model_hash'],
            'analysis_hash': digest(analysis), 'analysis': analysis,
            'review_state': 'OWNER_REVIEW_REQUIRED', 'runtime_integration_verified': False,
            'market_evidence_verified': False,
            'requested_action': 'Review assumptions, scope and provenance; no automatic dispatch.',
            **flags()}
    return dict(body, handoff_hash=digest(body))
