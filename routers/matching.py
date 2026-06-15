import json
import re

# ── 내부 유틸 함수들 ────────────────────────────────────────────────

def _safe_json_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        return [parsed]
    except (json.JSONDecodeError, TypeError):
        return [value]

def _flatten_to_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_to_text(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten_to_text(v) for v in value)
    return str(value)

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9+#.]{2,}")
_MIN_KEYWORD_LEN = 2
_MIN_CONTAINMENT_LEN = 3

def _add_keyword(keywords, value):
    value = value.strip().lower()
    if len(value) >= _MIN_KEYWORD_LEN:
        keywords.add(value)

def _extract_keywords(*raw_values):
    keywords = set()
    for raw in raw_values:
        if not raw:
            continue
        if isinstance(raw, str) and raw.strip().startswith("["):
            for item in _safe_json_list(raw):
                text = _flatten_to_text(item)
                for token in _TOKEN_RE.findall(text):
                    _add_keyword(keywords, token)
            continue
        text = _flatten_to_text(raw)
        for chunk in re.split(r"[,/;\n]", text):
            _add_keyword(keywords, chunk)
        for token in _TOKEN_RE.findall(text):
            _add_keyword(keywords, token)
    return keywords

def _overlap(set_a, set_b):
    """
    [핵심 수정 1] 중복 매칭 방지 로직 적용
    한 번 매칭된 타겟 단어는 다시 사용되지 않도록 used_b로 관리합니다.
    긴 단어부터 매칭하여 '개발', '웹개발'이 '웹개발자' 하나에 중복으로 붙지 않게 합니다.
    """
    matched = set()
    if not set_a or not set_b:
        return matched

    list_a = sorted(list(set_a), key=len, reverse=True)
    list_b = sorted(list(set_b), key=len, reverse=True)
    used_b = set()

    for a in list_a:
        if not a:
            continue
        
        exact_match = False
        # 1. 완전 일치 우선 검사
        for b in list_b:
            if b in used_b:
                continue
            if a == b:
                matched.add(a)
                used_b.add(b)
                exact_match = True
                break
        
        if exact_match:
            continue
            
        # 2. 부분 일치 검사
        for b in list_b:
            if b in used_b:
                continue
            if a.isdigit() or b.isdigit():
                continue
            if len(a) < _MIN_CONTAINMENT_LEN or len(b) < _MIN_CONTAINMENT_LEN:
                continue
            
            if (a in b) or (b in a):
                # 표시할 때는 더 짧고 대중적인 키워드로 저장
                matched.add(a if len(a) <= len(b) else b)
                used_b.add(b)
                break

    return matched


# ── 매칭 점수 계산 ───────────────────────────────────────────────────

def calc_match_score(current_user, mentor_user, mentor_profile=None):
    if current_user is None or mentor_user is None:
        return 0, []

    score = 0
    reasons = []
    
    # [핵심 수정 2] 항목 간 점수 중복(우려먹기)을 막기 위한 전역 집합
    global_matched = set()

    # ── 1. 멘티(나)가 가진 정보 ──
    my_learn_kw = _extract_keywords(getattr(current_user, "help_receive", None))
    my_provide_kw = _extract_keywords(getattr(current_user, "help_provide", None))
    my_experience_kw = _extract_keywords(getattr(current_user, "experience", None))
    my_hashtag_kw = _extract_keywords(getattr(current_user, "hashtags", None))

    # ── 2. 멘토 쪽 정보 ──
    mentor_topic_kw = _extract_keywords(
        getattr(mentor_profile, "mentoring_topics", None) if mentor_profile else None,
        getattr(mentor_profile, "job_title", None) if mentor_profile else None,
        getattr(mentor_profile, "main_category", None) if mentor_profile else None,
        getattr(mentor_profile, "sub_category", None) if mentor_profile else None,
        getattr(mentor_profile, "mentor_intro", None) if mentor_profile else None,
    )
    mentor_career_kw = _extract_keywords(
        getattr(mentor_profile, "career_history", None) if mentor_profile else None,
        getattr(mentor_profile, "detailed_experience", None) if mentor_profile else None,
        getattr(mentor_profile, "job_title", None) if mentor_profile else None,
        getattr(mentor_profile, "main_category", None) if mentor_profile else None,
        getattr(mentor_profile, "sub_category", None) if mentor_profile else None,
    )
    mentor_provide_kw = _extract_keywords(getattr(mentor_user, "help_provide", None))
    mentor_receive_kw = _extract_keywords(getattr(mentor_user, "help_receive", None))
    mentor_hashtag_kw = _extract_keywords(getattr(mentor_user, "hashtags", None))

    # ── 3. 항목별 매칭 & 점수 부여 ──

    # (1) 내가 배우고 싶은 분야 
    learn_match = _overlap(my_learn_kw, mentor_topic_kw | mentor_career_kw | mentor_provide_kw)
    if learn_match:
        score += 40 * len(learn_match)
        reasons.append(f"배우고 싶은 분야({', '.join(sorted(learn_match)[:3])})와 멘토의 전문 분야가 잘 맞아요")
        global_matched.update(learn_match) # 점수 받은 단어 등록

    # (2) 내 경력/이력
    # 이미 점수를 받은 단어(global_matched)는 제외하여 중복 점수를 막음
    career_match = _overlap(my_experience_kw, mentor_career_kw) - global_matched
    if career_match:
        score += 20 * len(career_match)
        reasons.append(f"경력 분야({', '.join(sorted(career_match)[:3])})가 비슷해 공감대를 형성하기 좋아요")
        global_matched.update(career_match)

    # (3) 상호 교환형 매칭
    mutual_match = _overlap(my_provide_kw, mentor_receive_kw) - global_matched
    if mutual_match:
        score += 15 * len(mutual_match)
        reasons.append(f"내가 도움을 줄 수 있는 분야({', '.join(sorted(mutual_match)[:3])})를 멘토님도 필요로 해요")
        global_matched.update(mutual_match)

    # (4) 해시태그 / 관심 키워드
    hashtag_match = _overlap(my_hashtag_kw, mentor_hashtag_kw | mentor_topic_kw) - global_matched
    if hashtag_match:
        score += 5 * len(hashtag_match)
        reasons.append(f"공통 관심 키워드({', '.join(sorted(hashtag_match)[:3])})가 있어요")

    return score, reasons