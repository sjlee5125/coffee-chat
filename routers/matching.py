"""
멘토 추천 매칭 알고리즘
─────────────────────────────────────────────────────────────
멘티(현재 로그인한 사용자, current_user)의 프로필 정보와
멘토(mentor_user / mentor_profile)의 프로필 정보를 비교해
얼마나 잘 맞는지(match_score)와 그 이유(reasons)를 계산합니다.

매칭에 사용하는 멘티 측 정보 (User 테이블)
  - help_receive  : "배우고 싶은 분야"            → 가중치 가장 높음
  - experience    : "주요 이력 및 경력 사항"       → 비슷한 배경 매칭
  - help_provide  : "내가 확실히 도움을 줄 수 있는 분야" → 상호 교환형 매칭
  - hashtags      : 관심 키워드 (보너스)

매칭에 사용하는 멘토 측 정보
  - Mentor.mentoring_topics / job_title / main_category / sub_category / mentor_intro
  - Mentor.career_history / detailed_experience
  - User(mentor).help_provide / help_receive / hashtags

단순 완전 일치뿐 아니라, 한쪽 키워드가 다른쪽 키워드에 "부분 문자열"로
포함되는 경우도 매칭으로 인정해서 최대한 많은 항목이 매칭되도록 합니다.
(예: 내가 적은 "백엔드"가 멘토의 "백엔드 개발자" 안에 포함되는 경우)
"""

import json
import re


# ── 내부 유틸 함수들 ────────────────────────────────────────────────

def _safe_json_list(value):
    """JSON 배열 문자열을 파싱합니다. 실패하거나 배열이 아니면 적절히 보정합니다."""
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
    """문자열/딕셔너리/리스트 등 어떤 구조든 검색 가능한 하나의 텍스트로 합칩니다."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_to_text(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten_to_text(v) for v in value)
    return str(value)


# 한글/영문/숫자/+,# 등으로 이루어진 2글자 이상 토큰만 의미있는 키워드로 인정
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9+#.]{2,}")

# 키워드로 인정할 최소 글자 수. 이보다 짧은 조각(예: "2", "a")은
# 의미 없는 매칭(예: "B2B"의 "2"와 우연히 겹치는 경우)을 유발하므로 제외합니다.
_MIN_KEYWORD_LEN = 2

# 부분 문자열 포함 매칭을 적용할 최소 글자 수.
# "b2"가 "b2b"에 포함된다고 매칭시키는 식의 우연한 매칭을 방지합니다.
_MIN_CONTAINMENT_LEN = 3


def _add_keyword(keywords, value):
    """길이 조건(_MIN_KEYWORD_LEN 이상)을 만족하는 키워드만 집합에 추가합니다."""
    value = value.strip().lower()
    if len(value) >= _MIN_KEYWORD_LEN:
        keywords.add(value)


def _extract_keywords(*raw_values):
    """
    여러 소스(콤마로 구분된 태그 문자열, JSON 배열 문자열, 자유 서술형 텍스트 등)에서
    중복 제거된 키워드 집합을 추출합니다.
    """
    keywords = set()

    for raw in raw_values:
        if not raw:
            continue

        # 1) JSON 배열 형태("[...]")로 저장된 필드는 먼저 펼쳐서 처리
        if isinstance(raw, str) and raw.strip().startswith("["):
            for item in _safe_json_list(raw):
                text = _flatten_to_text(item)
                for token in _TOKEN_RE.findall(text):
                    _add_keyword(keywords, token)
            continue

        text = _flatten_to_text(raw)

        # 2) 콤마/슬래시/세미콜론/줄바꿈 등으로 구분된 "태그형" 표현 우선 처리
        for chunk in re.split(r"[,/;\n]", text):
            _add_keyword(keywords, chunk)

        # 3) 자유 서술형 텍스트에서도 단어 단위 토큰을 추출 (부분 매칭용)
        for token in _TOKEN_RE.findall(text):
            _add_keyword(keywords, token)

    return keywords


def _overlap(set_a, set_b):
    """
    두 키워드 집합 사이의 교집합을 구합니다.

    - 완전히 같은 키워드는 항상 매칭으로 인정합니다.
    - 한쪽이 다른쪽의 부분 문자열인 경우도 매칭으로 인정해서
      (예: "백엔드" ⊂ "백엔드개발자") 최대한 많은 항목을 찾아내지만,
      다음 두 경우는 "우연한 매칭"을 막기 위해 제외합니다.
        1) 두 키워드 중 하나라도 _MIN_CONTAINMENT_LEN(3글자)보다 짧은 경우
           예) "b2"가 "b2b"에 포함된다고 해서 매칭으로 보지 않음
        2) 두 키워드 중 하나라도 숫자로만 이루어진 경우
           예) "2"가 "b2b"나 "2023"에 포함된다고 해서 매칭으로 보지 않음
           (숫자 키워드는 완전히 동일한 경우에만 매칭)
    """
    matched = set()
    if not set_a or not set_b:
        return matched

    for a in set_a:
        if not a:
            continue
        for b in set_b:
            if not b:
                continue

            if a == b:
                matched.add(a)
                break

            # 숫자로만 된 키워드는 완전 일치가 아니면 매칭으로 인정하지 않음
            if a.isdigit() or b.isdigit():
                continue

            # 너무 짧은 키워드끼리의 부분 문자열 포함은 우연한 매칭일 가능성이 높음
            if len(a) < _MIN_CONTAINMENT_LEN or len(b) < _MIN_CONTAINMENT_LEN:
                continue

            if (a in b) or (b in a):
                # 더 짧은(=더 구체적인 일반 키워드) 쪽을 표시 키워드로 사용
                matched.add(a if len(a) <= len(b) else b)
                break

    return matched


# ── 매칭 점수 계산 ───────────────────────────────────────────────────

def calc_match_score(current_user, mentor_user, mentor_profile=None):
    """
    현재 사용자(current_user)와 멘토(mentor_user / mentor_profile)의
    프로필을 비교해 매칭 점수(score)와 매칭 이유 목록(reasons)을 반환합니다.

    Parameters
    ----------
    current_user : models.User
        추천을 받는 멘티(나) 정보
    mentor_user : models.User
        멘토의 User 레코드 (help_provide / help_receive / hashtags 등)
    mentor_profile : models.Mentor | None
        멘토의 Mentor 레코드 (mentoring_topics / career_history 등).
        라우터에서 (User, Mentor) JOIN 결과로 함께 들고 있으므로 그대로 전달하면 됩니다.

    Returns
    -------
    (score: int, reasons: list[str])
    """

    if current_user is None or mentor_user is None:
        return 0, []

    score = 0
    reasons = []

    # ── 1. 멘티(나)가 가진 정보 ─────────────────────────────────────
    my_learn_kw = _extract_keywords(
        getattr(current_user, "help_receive", None),   # 배우고 싶은 분야
    )
    my_provide_kw = _extract_keywords(
        getattr(current_user, "help_provide", None),   # 내가 확실히 도움을 줄 수 있는 분야
    )
    my_experience_kw = _extract_keywords(
        getattr(current_user, "experience", None),      # 주요 이력 및 경력 사항
    )
    my_hashtag_kw = _extract_keywords(
        getattr(current_user, "hashtags", None),
    )

    # ── 2. 멘토 쪽 정보 ─────────────────────────────────────────────
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
    mentor_provide_kw = _extract_keywords(
        getattr(mentor_user, "help_provide", None),
    )
    mentor_receive_kw = _extract_keywords(
        getattr(mentor_user, "help_receive", None),
    )
    mentor_hashtag_kw = _extract_keywords(
        getattr(mentor_user, "hashtags", None),
    )

    # ── 3. 항목별 매칭 & 점수 부여 ──────────────────────────────────

    # (1) 내가 배우고 싶은 분야 ↔ 멘토의 전문분야 / 경력 / 소개 / 제공 가능한 도움
    #     → 가장 핵심적인 매칭이므로 가중치를 가장 높게 설정
    learn_match = _overlap(
        my_learn_kw,
        mentor_topic_kw | mentor_career_kw | mentor_provide_kw,
    )
    if learn_match:
        score += 40 * len(learn_match)
        reasons.append(
            f"배우고 싶은 분야({', '.join(sorted(learn_match)[:3])})와 멘토의 전문 분야가 잘 맞아요"
        )

    # (2) 내 경력/이력 ↔ 멘토의 경력 / 직무 / 카테고리
    #     → 비슷한 커리어 배경을 가진 멘토를 우선 추천
    career_match = _overlap(my_experience_kw, mentor_career_kw)
    if career_match:
        score += 20 * len(career_match)
        reasons.append(
            f"경력 분야({', '.join(sorted(career_match)[:3])})가 비슷해 공감대를 형성하기 좋아요"
        )

    # (3) 내가 도움을 줄 수 있는 분야 ↔ 멘토가 도움 받고 싶어하는 분야
    #     → 서로 주고받을 수 있는 "상호 교환형" 매칭
    mutual_match = _overlap(my_provide_kw, mentor_receive_kw)
    if mutual_match:
        score += 15 * len(mutual_match)
        reasons.append(
            f"내가 도움을 줄 수 있는 분야({', '.join(sorted(mutual_match)[:3])})를 멘토님도 필요로 해요"
        )

    # (4) 해시태그 / 관심 키워드 겹침 → 보너스 점수
    hashtag_match = _overlap(my_hashtag_kw, mentor_hashtag_kw | mentor_topic_kw)
    if hashtag_match:
        score += 5 * len(hashtag_match)
        reasons.append(
            f"공통 관심 키워드({', '.join(sorted(hashtag_match)[:3])})가 있어요"
        )

    return score, reasons