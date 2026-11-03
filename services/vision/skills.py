"""Scenario skills: folders that tell Muse how SAM 3.1 handles a scenario, plus an optional VLM check.

skills/<id>/skill.json   what the scenario needs: rule template, keywords, optional VLM check
skills/<id>/knowledge.md plant notes, prompt words that work on this camera, known limits
skills/_site/knowledge.md notes for every request (optional)

Anyone can add or edit a skill without code. Skills reach Muse as reference data only;
the app still validates every proposal, and a VLM check never changes Active or State.
"""
import json
import re
from pathlib import Path

from .assistant import JOINS, OUTPUT_NAME, OUTPUT_TYPES, RELATIONS

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / 'skills'
SKILL_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,47}')
STATUSES = ('ready', 'experimental')
VLM_MODES = ('confirm', 'scene', 'classify')
TRIGGERS = ('on_active', 'periodic')
RULE_FIELDS = {'target': str, 'secondTarget': str, 'firstRelation': str, 'secondRelation': str, 'join': str,
               'persistence': (int, float), 'outputType': str, 'output': str}
WORD = re.compile(r'[a-z0-9]+')
STOP = {'a', 'an', 'the', 'and', 'or', 'of', 'to', 'in', 'on', 'is', 'are', 'for', 'when', 'if', 'it', 'be',
        'with', 'at', 'by', 'this', 'that', 'from', 'as', 'any', 'all'}


class SkillError(ValueError):
    pass


def text(value, name, limit, empty=False):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value or (not empty and not value.strip()):
        raise SkillError(f'{name}: text up to {limit} characters.')
    return value.strip()


def validate(data, folder_name, knowledge=''):
    if not isinstance(data, dict):
        raise SkillError('skill.json must be a JSON object.')
    if data.get('id') != folder_name or not SKILL_ID.fullmatch(folder_name):
        raise SkillError('id must equal the folder name: lowercase letters, digits and hyphens.')
    keywords = data.get('keywords', [])
    if not isinstance(keywords, list) or len(keywords) > 30:
        raise SkillError('keywords: a list of up to 30 words.')
    skill = dict(id=folder_name, name=text(data.get('name'), 'name', 80), summary=text(data.get('summary'), 'summary', 400),
                 keywords=[text(k, 'keyword', 40).lower() for k in keywords],
                 status=data.get('status', 'experimental'), knowledge=text(knowledge, 'knowledge.md', 8000, empty=True))
    if skill['status'] not in STATUSES:
        raise SkillError('status: ready or experimental.')
    rule = data.get('rule', {})
    if not isinstance(rule, dict) or set(rule) - set(RULE_FIELDS):
        raise SkillError('rule: only ' + ', '.join(RULE_FIELDS) + '.')
    for key, value in rule.items():
        if not isinstance(value, RULE_FIELDS[key]) or isinstance(value, bool):
            raise SkillError(f'rule.{key} has the wrong type.')
    for key, allowed in (('firstRelation', RELATIONS), ('secondRelation', RELATIONS), ('join', JOINS), ('outputType', OUTPUT_TYPES)):
        if key in rule and rule[key] not in allowed:
            raise SkillError(f'rule.{key} must be one of: ' + ', '.join(allowed) + '.')
    if 'output' in rule and not OUTPUT_NAME.fullmatch(rule['output']):
        raise SkillError('rule.output is not a valid tag name.')
    if 'persistence' in rule and not 0 <= rule['persistence'] <= 60:
        raise SkillError('rule.persistence: 0 to 60 seconds.')
    skill['rule'] = rule
    vlm = data.get('vlm')
    if vlm is not None:
        if not isinstance(vlm, dict) or vlm.get('mode') not in VLM_MODES or vlm.get('trigger') not in TRIGGERS:
            raise SkillError('vlm: mode confirm/scene/classify and trigger on_active/periodic.')
        answers = vlm.get('answers')
        if not isinstance(answers, list) or not 2 <= len(answers) <= 6 or len(set(answers)) != len(answers):
            raise SkillError('vlm.answers: 2 to 6 different short answers.')
        interval = vlm.get('interval_seconds', 60)
        if type(interval) not in (int, float) or not 20 <= interval <= 3600:
            raise SkillError('vlm.interval_seconds: 20 to 3600.')
        vlm = dict(mode=vlm['mode'], trigger=vlm['trigger'], question=text(vlm.get('question'), 'vlm.question', 400),
                   answers=[text(a, 'vlm answer', 40) for a in answers], interval_seconds=interval)
    skill['vlm'] = vlm
    return skill


def load(folder=FOLDER):
    """All valid skills, and the problems of the invalid ones (shown, never fatal)."""
    skills, problems = {}, []
    folder = Path(folder)
    if not folder.is_dir():
        return skills, problems
    for path in sorted(folder.iterdir()):
        if not path.is_dir() or path.name.startswith('_'):
            continue
        try:
            data = json.loads((path / 'skill.json').read_text(encoding='utf-8'))
            notes = path / 'knowledge.md'
            skills[path.name] = validate(data, path.name, notes.read_text(encoding='utf-8') if notes.exists() else '')
        except (OSError, ValueError) as error:
            problems.append(f'{path.name}: {error}')
    return skills, problems


def site_notes(folder=FOLDER):
    try:
        return text((Path(folder) / '_site' / 'knowledge.md').read_text(encoding='utf-8'), 'site notes', 4000, empty=True)
    except (OSError, SkillError):
        return ''


def words(value):
    return [w for w in WORD.findall(value.lower()) if w not in STOP and len(w) > 1]


def search(request, skills, limit=3):
    """Keyword lookup: skill keywords weigh most, then name, summary and notes. No vector database needed."""
    query = set(words(request))
    scored = []
    for skill in skills.values():
        keywords = set(w for k in skill['keywords'] for w in words(k))
        score = (3 * len(query & keywords) + 2 * len(query & set(words(skill['name'])))
                 + len(query & set(words(skill['summary']))) + .5 * len(query & set(words(skill['knowledge']))))
        if score:
            scored.append((score, skill['id']))
    return [skills[skill_id] for _, skill_id in sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]]


def reference(matches, notes=''):
    """What Muse receives: short data records, never instructions."""
    return dict(site_notes=notes[:1500], skills=[dict(id=s['id'], name=s['name'], status=s['status'], summary=s['summary'],
        rule_template=s['rule'], vlm_check=(s['vlm'] or {}).get('question', ''), notes=s['knowledge'][:1500]) for s in matches])


def public(skill):
    """Skill fields the UI shows."""
    return None if skill is None else dict(id=skill['id'], name=skill['name'], status=skill['status'], summary=skill['summary'],
                                           vlm=skill['vlm'])
