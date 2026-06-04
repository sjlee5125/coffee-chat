# routers/matching.py

import json
import re


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
        except:
            return [s.strip().lower() for s in re.split(r'[,\s]+', data) if s.strip()]
    return [str(data).strip().lower()]


def parse_experience_texts(data):
    if not data:
        return []
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except:
            return [data.lower()]
    if isinstance(data, list):
        texts = []
        for item in data:
            if isinstance(item, dict):
                texts.append(str(item.get('text', '')).lower())
            else:
                texts.append(str(item).lower())
        return texts
    return []


def tokenize(text):
    if not text:
        return set()
    return set(re.findall(r'[가-힣]+|[a-zA-Z]+', text.lower()))


def calc_match_score(user, mentor):
    score = 0
    match_reasons = []

    user_help_receive   = parse_field(user.help_receive)
    user_hashtags       = parse_field(user.hashtags)
    user_experience     = parse_field(user.experience)
    user_help_provide   = parse_field(user.help_provide)
    user_main_cat       = (user.main_category or '').lower()
    user_sub_cat        = (user.sub_category or '').lower()
    user_bio_tokens     = tokenize(user.bio or '')
    user_mbti           = (user.mbti or '').upper()

    mentor_keywords     = parse_field(mentor.mentor_keywords)
    mentor_topics       = parse_field(mentor.mentoring_topics)
    mentor_hashtags     = parse_field(mentor.hashtags)
    mentor_exp_texts    = parse_experience_texts(mentor.detailed_experience)
    mentor_career       = parse_field(mentor.career_history)
    mentor_main_cat     = (mentor.main_category or '').lower()
    mentor_sub_cat      = (mentor.sub_category or '').lower()
    mentor_bio_tokens   = tokenize(mentor.bio or mentor.mentor_intro or '')
    mentor_mbti         = (mentor.mbti or '').upper()
    mentor_story_tokens = tokenize(mentor.mentor_intro or '')

    # 1. help_receive ↔ mentor_keywords +15
    for kw in user_help_receive:
        if any(kw in mk or mk in kw for mk in mentor_keywords):
            score += 15
            match_reasons.append(f"관심분야↔키워드: {kw}")

    # 2. help_receive ↔ mentoring_topics +12
    for kw in user_help_receive:
        if any(kw in mt or mt in kw for mt in mentor_topics):
            score += 12
            match_reasons.append(f"관심분야↔주제: {kw}")

    # 3. help_receive ↔ detailed_experience +10
    for kw in user_help_receive:
        kw_tokens = tokenize(kw)
        for exp_text in mentor_exp_texts:
            if kw_tokens & tokenize(exp_text):
                score += 10
                match_reasons.append(f"관심분야↔경험: {kw_tokens & tokenize(exp_text)}")
                break

    # 4. 직무 카테고리 일치 +10 / 세부직무 +7
    if user_main_cat and user_main_cat == mentor_main_cat:
        score += 10
        match_reasons.append(f"주직무 일치: {user_main_cat}")
    if user_sub_cat and user_sub_cat == mentor_sub_cat:
        score += 7
        match_reasons.append(f"세부직무 일치: {user_sub_cat}")

    # 5. hashtags 교집합 +8
    tag_overlap = set(user_hashtags) & set(mentor_hashtags)
    if tag_overlap:
        score += len(tag_overlap) * 8
        match_reasons.append(f"해시태그 겹침: {tag_overlap}")

    # 6. help_receive ↔ career_history +6
    for kw in user_help_receive:
        kw_tokens = tokenize(kw)
        for career in mentor_career:
            if kw_tokens & tokenize(career):
                score += 6
                match_reasons.append(f"관심분야↔경력: {kw}")
                break

    # 7. user hashtags ↔ mentor keywords/topics +5
    for tag in user_hashtags:
        if any(tag in mk or mk in tag for mk in mentor_keywords + mentor_topics):
            score += 5
            match_reasons.append(f"해시태그↔키워드: {tag}")

    # 8. user experience ↔ mentor keywords +4
    for exp in user_experience:
        exp_tokens = tokenize(exp)
        for mk in mentor_keywords + mentor_topics:
            if exp_tokens & tokenize(mk):
                score += 4
                match_reasons.append(f"경력↔키워드: {exp}")
                break

    # 9. bio 토큰 교집합 +3 (최대 15)
    meaningful = {t for t in (user_bio_tokens & mentor_bio_tokens) if len(t) >= 2}
    if meaningful:
        score += min(len(meaningful) * 3, 15)
        match_reasons.append(f"자기소개 유사: {list(meaningful)[:3]}")

    # 10. help_provide ↔ mentor hashtags +3
    for hp in user_help_provide:
        hp_tokens = tokenize(hp)
        for mh in mentor_hashtags:
            if hp_tokens & tokenize(mh):
                score += 3
                match_reasons.append(f"제공분야↔해시태그: {hp}")
                break

    # 11. MBTI 일치 +2
    if user_mbti and mentor_mbti and user_mbti == mentor_mbti:
        score += 2
        match_reasons.append(f"MBTI 일치: {user_mbti}")

    # 12. help_receive ↔ mentor_story +2
    for kw in user_help_receive:
        if tokenize(kw) & mentor_story_tokens:
            score += 2
            match_reasons.append(f"관심분야↔스토리: {kw}")

    return score, match_reasons