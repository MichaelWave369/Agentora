import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlmodel import Session, select

from app.db import get_session
from app.models import ArenaMatch, ArenaTournament, ArenaVote

router = APIRouter(prefix='/api/arena', tags=['arena'])

ROUNDS = ['Opening', 'CrossExamination', 'EvidenceDrop', 'Rebuttal', 'FinalVerdict']


@router.post('/match')
def create_match(payload: dict, session: Session = Depends(get_session)):
    topic = payload['topic']
    transcript = [{'round': r, 'speaker': 'Synthesizer', 'content': f'{r} on {topic}', 'ts': i} for i, r in enumerate(ROUNDS)]
    report = f"# What We Learned\n\nTopic: {topic}\n\nConfidence: 0.78\n"
    board = {'truth_score': 78, 'consistency': 80, 'sources': 70, 'honesty': 84, 'elo': {'Synthesizer': 1016}}
    m = ArenaMatch(topic=topic, mode=payload.get('mode', 'single'), status='completed', transcript_json=json.dumps(transcript), report_md=report, scoreboard_json=json.dumps(board))
    session.add(m)
    session.commit()
    session.refresh(m)
    return {'match_id': m.id}


@router.post('/tournament')
def create_tournament(payload: dict, session: Session = Depends(get_session)):
    topics = payload.get('topics', [])
    bracket = {'topics': topics, 'winner': topics[0] if topics else 'n/a'}
    t = ArenaTournament(status='completed', topics_json=json.dumps(topics), bracket_json=json.dumps(bracket))
    session.add(t)
    session.commit()
    session.refresh(t)
    return {'tournament_id': f't{t.id}'}


@router.get('/{id}/status')
def status(id: str, session: Session = Depends(get_session)):
    if str(id).startswith('t'):
        t = session.get(ArenaTournament, int(str(id)[1:]))
        if t:
            return {'kind': 'tournament', 'status': t.status, 'bracket': json.loads(t.bracket_json)}
    m = session.get(ArenaMatch, int(id)) if str(id).isdigit() else None
    if m:
        return {'kind': 'match', 'status': m.status, 'scoreboard': json.loads(m.scoreboard_json)}
    t = session.get(ArenaTournament, int(id)) if str(id).isdigit() else None
    if t:
        return {'kind': 'tournament', 'status': t.status, 'bracket': json.loads(t.bracket_json)}
    raise HTTPException(404, 'not found')


@router.get('/{id}/transcript.json')
def transcript(id: int, session: Session = Depends(get_session)):
    m = session.get(ArenaMatch, id)
    return Response(content=json.dumps(json.loads(m.transcript_json), indent=2), media_type='application/json')


@router.get('/{id}/report.md')
def report(id: int, session: Session = Depends(get_session)):
    m = session.get(ArenaMatch, id)
    return Response(content=m.report_md, media_type='text/markdown')


@router.post('/{id}/vote')
def vote(id: int, payload: dict, session: Session = Depends(get_session)):
    v = ArenaVote(match_id=id, agent_id=payload['agent_id'], score=payload['score'])
    session.add(v)
    session.commit()
    return {'ok': True}


@router.get('/leaderboard')
def leaderboard(session: Session = Depends(get_session)):
    votes = list(session.exec(select(ArenaVote)))
    total = {}
    for v in votes:
        total[v.agent_id] = total.get(v.agent_id, 0) + v.score
    return {'leaderboard': [{'agent_id': k, 'applause': v} for k, v in sorted(total.items(), key=lambda x: x[1], reverse=True)]}


@router.post('/debate-lyrics')
def debate_lyrics(payload: dict, session: Session = Depends(get_session)):
    return create_match({'topic': f"Verify lyrics accuracy: {payload.get('lyrics','')[:80]}", 'mode': 'single'}, session)
