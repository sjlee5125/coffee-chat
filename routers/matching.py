# routers/matching.py

import json
import re


def get_value(obj, field, default=None):
    """SQLAlchemy 객체/딕셔너리에서 안전하게 값 꺼내기"""
    if obj is None:
        return default

    if isinstance(obj, dict):
        return obj.get(field, default)

    return getattr(obj, field, default)


def parse_field(data):
    if not data:
        return []

    if isinstance(data, list):
        return [str(s).strip().lower() for s in data if s]

    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            if isinstance(parsed, list):
                return [str(s).strip().lower() for s in parsed if s]
            return [str(parsed).strip().lower()]
        except Exception:
            return [s.strip().lower() for s in re.split(r"[,\s]+", data) if s.strip()]

    return [str(data).strip().lower()]


def parse_experience_texts(data):
    if not data:
        return []

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return [data.lower()]

    if isinstance(data, list):
        texts = []
        for item in data:
            if isinstance(item, dict):
                texts.append(str(item.get("text", "")).lower())
            else:
                texts.append(str(item).lower())
        return texts

    return []


def tokenize(text):
    if not text:
        return set()

    # 한글, 영어, 숫자 토큰 추출
    return set(re.findall(r"[가-힣a-zA-Z0-9]+", str(text).lower()))


def calc_match_score(user, mentor, mentor_user=None):
    score = 0
    match_reasons = []

    # user는 현재 로그인한 사용자(User)
    user_help_receive = parse_field(get_value(user, "help_receive", ""))
    user_hashtags = parse_field(get_value(user, "hashtags", ""))
    user_experience = parse_field(get_value(user, "experience", ""))
    user_help_provide = parse_field(get_value(user, "help_provide", ""))

    # User 테이블에 main_category/sub_category가 없을 수 있으므로 안전하게 처리
    user_main_cat = str(get_value(user, "main_category", "") or "").lower()
    user_sub_cat = str(get_value(user, "sub_category", "") or "").lower()
    user_bio_tokens = tokenize(get_value(user, "bio", "") or "")
    user_mbti = str(get_value(user, "mbti", "") or "").upper()

    # mentor는 Mentor 객체
    mentor_keywords = parse_field(
        get_value(mentor, "mentor_keywords", None)
        or get_value(mentor, "mentoring_topics", "")
    )
    mentor_topics = parse_field(get_value(mentor, "mentoring_topics", ""))
    mentor_exp_texts = parse_experience_texts(get_value(mentor, "detailed_experience", ""))
    mentor_career = parse_field(get_value(mentor, "career_history", ""))

    mentor_main_cat = str(get_value(mentor, "main_category", "") or "").lower()
    mentor_sub_cat = str(get_value(mentor, "sub_category", "") or "").lower()
    mentor_intro = get_value(mentor, "mentor_intro", "") or ""

    # mentor_user는 멘토의 User 객체. 해시태그/자기소개/MBTI 등이 User에 있을 수 있음
    mentor_hashtags = parse_field(get_value(mentor_user, "hashtags", ""))
    mentor_user_bio = get_value(mentor_user, "bio", "") or ""
    mentor_bio_tokens = tokenize(mentor_user_bio or mentor_intro)
    mentor_mbti = str(get_value(mentor_user, "mbti", "") or "").upper()
    mentor_story_tokens = tokenize(mentor_intro)

    # 1. 사용자가 받고 싶은 도움과 멘토 키워드 매칭 +15
    for kw in user_help_receive:
        if any(kw in mk or mk in kw for mk in mentor_keywords):
            score += 15
            match_reasons.append(f"관심 키워드 일치: {kw}")

    # 2. 사용자가 받고 싶은 도움과 멘토링 주제 매칭 +12
    for kw in user_help_receive:
        if any(kw in mt or mt in kw for mt in mentor_topics):
            score += 12
            match_reasons.append(f"멘토링 주제 일치: {kw}")

    # 3. 사용자가 받고 싶은 도움과 멘토 상세 경험 매칭 +10
    for kw in user_help_receive:
        kw_tokens = tokenize(kw)
        for exp_text in mentor_exp_texts:
            overlap = kw_tokens & tokenize(exp_text)
            if overlap:
                score += 10
                match_reasons.append(f"관련 경험 일치: {', '.join(list(overlap)[:3])}")
                break

    # 4. 직무 카테고리 일치 +10 / 세부 직무 일치 +7
    if user_main_cat and mentor_main_cat and user_main_cat == mentor_main_cat:
        score += 10
        match_reasons.append(f"직무 카테고리 일치: {user_main_cat}")

    if user_sub_cat and mentor_sub_cat and user_sub_cat == mentor_sub_cat:
        score += 7
        match_reasons.append(f"세부 직무 일치: {user_sub_cat}")

    # 5. 해시태그 겹침 +8
    tag_overlap = set(user_hashtags) & set(mentor_hashtags)
    if tag_overlap:
        score += len(tag_overlap) * 8
        match_reasons.append(f"해시태그 일치: {', '.join(list(tag_overlap)[:3])}")

    # 6. 사용자가 받고 싶은 도움과 멘토 경력 매칭 +6
    for kw in user_help_receive:
        kw_tokens = tokenize(kw)
        for career in mentor_career:
            if kw_tokens & tokenize(career):
                score += 6
                match_reasons.append(f"관련 경력 일치: {kw}")
                break

    # 7. 사용자 해시태그와 멘토 키워드/주제 매칭 +5
    for tag in user_hashtags:
        if any(tag in mk or mk in tag for mk in mentor_keywords + mentor_topics):
            score += 5
            match_reasons.append(f"해시태그-키워드 일치: {tag}")

    # 8. 사용자 경험과 멘토 키워드 매칭 +4
    for exp in user_experience:
        exp_tokens = tokenize(exp)
        for mk in mentor_keywords + mentor_topics:
            if exp_tokens & tokenize(mk):
                score += 4
                match_reasons.append(f"경험-키워드 일치: {exp}")
                break

    # 9. 자기소개 토큰 겹침 +3, 최대 15점
    meaningful = {t for t in (user_bio_tokens & mentor_bio_tokens) if len(t) >= 2}
    if meaningful:
        score += min(len(meaningful) * 3, 15)
        match_reasons.append(f"자기소개 유사: {', '.join(list(meaningful)[:3])}")

    # 10. 사용자가 제공 가능한 도움과 멘토 해시태그 매칭 +3
    for hp in user_help_provide:
        hp_tokens = tokenize(hp)
        for mh in mentor_hashtags:
            if hp_tokens & tokenize(mh):
                score += 3
                match_reasons.append(f"제공 분야 일치: {hp}")
                break

    # 11. MBTI 일치 +2
    if user_mbti and mentor_mbti and user_mbti == mentor_mbti:
        score += 2
        match_reasons.append(f"MBTI 일치: {user_mbti}")

    # 12. 사용자가 받고 싶은 도움과 멘토 소개글 매칭 +2
    for kw in user_help_receive:
        if tokenize(kw) & mentor_story_tokens:
            score += 2
            match_reasons.append(f"멘토 소개글 관련: {kw}")

    # 같은 이유가 너무 많이 중복되지 않게 정리
    unique_reasons = []
    for reason in match_reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)

    return score, unique_reasons