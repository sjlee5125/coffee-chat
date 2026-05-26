import os
import time
import datetime
import uuid
import hmac
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv() # .env 읽어오기

def send_solapi_sms(receiver_phone: str, message: str):
    """솔라피(Solapi) API를 사용하여 문자를 발송하는 함수입니다."""
    
    api_key = os.getenv("SOLAPI_API_KEY")
    api_secret = os.getenv("SOLAPI_API_SECRET")
    sender_phone = os.getenv("SOLAPI_SENDER")
    
    # 1. 솔라피 전용 보안 서명(Signature) 만들기
    date = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    salt = str(uuid.uuid4().hex)
    data = date + salt
    signature = hmac.new(
        api_secret.encode('utf-8'), 
        data.encode('utf-8'), 
        hashlib.sha256
    ).hexdigest()
    
    # 2. 헤더 및 데이터 세팅
    headers = {
        'Authorization': f'HMAC-SHA256 apiKey={api_key}, date={date}, salt={salt}, signature={signature}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "message": {
            "to": receiver_phone.replace("-", ""),  # 받는 사람 번호
            "from": sender_phone.replace("-", ""),  # 보내는 사람 (내 번호)
            "text": message                         # 보낼 내용
        }
    }
    
    # 3. 솔라피 서버로 발송 요청!
    try:
        response = requests.post("https://api.solapi.com/messages/v4/send", headers=headers, json=payload)
        result = response.json()
        
        if response.status_code == 200:
            print(f"✅ 솔라피 문자 발송 성공! (수신자: {receiver_phone})")
            return True
        else:
            print(f"❌ 솔라피 문자 발송 실패: {result}")
            return False
            
    except Exception as e:
        print(f"❌ 통신 에러 발생: {e}")
        return False