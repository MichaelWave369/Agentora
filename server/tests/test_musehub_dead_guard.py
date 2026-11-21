"""Regression guards for MuseHub's false-positive dead-code candidates.

These tests perform no external service calls, releases, or remote writes.
"""
from pathlib import Path
import runpy

from sqlmodel import Session, SQLModel, create_engine

from app import models
from app.core.config import settings
from app.integrations.agentception_client import AgentCeptionClient
from app.integrations.phios_client import PhiOSClient
from app.integrations.schemas import MemoryWriteRequest
from app.services.development_board.r1b_verifier_worker import Witness
from app.services.development_board.r1h_packet import BEFORE, TARGET
from app.services.memory import recall, remember


def test_htmlparser_witness_callbacks_are_runtime_entrypoints():
    parser = Witness()
    parser.feed('<html><main id="content">hello <span>world</span></main></html>')
    parser.close()
    assert parser.valid
    assert parser.stack == []
    main = next(e for e in parser.elements if e['tag'] == 'main')
    assert main['text'] == 'hello world'

    forbidden = Witness()
    forbidden.feed('<html><script>bad</script></html>')
    forbidden.close()
    assert not forbidden.valid

    malformed = Witness()
    malformed.feed('<main>text</section>')
    malformed.close()
    assert not malformed.valid


def test_sqlmodel_tables_registered_via_metadata():
    for cls in (models.Artifact, models.VoiceSetting):
        assert cls.__tablename__ in SQLModel.metadata.tables
        assert cls.__table__ is SQLModel.metadata.tables[cls.__tablename__]


def test_r1h_toy_fixture_is_exact_and_intentional():
    repo_root = Path(__file__).resolve().parents[2]
    assert (repo_root / TARGET).read_text(encoding='utf-8') == BEFORE


def test_memory_legacy_helpers_still_work_without_touching_real_data():
    database = create_engine('sqlite:///:memory:')
    SQLModel.metadata.create_all(database, tables=[models.MemoryItem.__table__])
    with Session(database) as session:
        remember(session, agent_id=17, key='test', value='retained')
        items = recall(session, agent_id=17)
        assert len(items) == 1
        assert items[0].key == 'test'
        assert items[0].value == 'retained'
    database.dispose()


def test_flagged_integration_methods_preserve_mock_contracts(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_integrations_mock', True)
    monkeypatch.setattr(settings, 'agentora_phios_enabled', False)
    monkeypatch.setattr(settings, 'agentora_agentception_enabled', False)

    artifact_result = AgentCeptionClient().list_job_artifacts('job-123')
    assert artifact_result['job_id'] == 'job-123'
    assert isinstance(artifact_result['artifacts'], list)

    request = MemoryWriteRequest(
        session_id='session-1', source_system='agentora', task_id='task-1',
        summary='mock-only', details='No external write.',
    )
    response = PhiOSClient().write_memory(request)
    assert response['ok'] is True
    assert response['mode'] == 'mock'


def test_health_audit_catalog_is_complete_and_read_only(tmp_path):
    root = Path(__file__).resolve().parents[2]
    audit = runpy.run_path(str(root / 'scripts/musehub_dead_audit.py'))
    assert len(audit['CANDIDATES']) == 28
    assert sum(row[2] == 'high' for row in audit['CANDIDATES']) == 3
    assert sum(row[2] == 'medium' for row in audit['CANDIDATES']) == 25

    # Create a disposable checkout so the scanner cannot affect real data.
    model_file = tmp_path / 'server/app/models.py'
    model_file.parent.mkdir(parents=True)
    model_file.write_text('class Artifact:\n    pass\n', encoding='utf-8')
    reference = tmp_path / 'caller.py'
    reference.write_text('from example import Artifact\nvalue = Artifact()\n')
    before = reference.read_bytes()
    result = audit['make_report'](tmp_path)
    assert result['candidate_count'] == 28
    artifact = next(r for r in result['candidates']
                    if r['symbol'] == 'server/app/models.py::Artifact')
    assert artifact['defined_in_checkout']
    assert artifact['other_file_ast_mentions'] >= 1
    assert all(row['safe_to_delete'] is False for row in result['candidates'])
    assert reference.read_bytes() == before
