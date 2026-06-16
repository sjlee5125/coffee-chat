from fastapi import APIRouter, UploadFile, File, HTTPException
from azure.storage.blob import BlobServiceClient, ContentSettings
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# .env에서 Azure 연결 키를 가져옵니다.
AZURE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CONTAINER_NAME = "imageupload"  # 대표님이 만드신 컨테이너 이름!

async def upload_to_azure(file: UploadFile):
    if not AZURE_CONNECTION_STRING:
        raise HTTPException(status_code=500, detail="Azure 연결 문자열이 설정되지 않았습니다.")
    
    try:
        # 1. Azure 서버와 연결
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
        
        # 2. 파일 이름이 겹치지 않도록 절대 겹치지 않는 난수(UUID)로 이름 변경
        file_extension = file.filename.split('.')[-1]
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        
        # 3. 업로드할 목적지 설정
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=unique_filename)
        
        # 4. 파일 읽기
        contents = await file.read()
        
        # 5. 브라우저에서 다운로드되지 않고 바로 보이도록 Content-Type 강제 지정
        content_settings = ContentSettings(content_type=file.content_type)
        
        # 6. Azure로 슛!
        blob_client.upload_blob(contents, overwrite=True, content_settings=content_settings)
        
        # 7. 성공적으로 올라갔다면 해당 파일의 인터넷 주소(URL) 반환
        return blob_client.url

    except Exception as e:
        print(f"🚨 Azure 업로드 실패: {e}")
        raise HTTPException(status_code=500, detail=f"Azure 업로드 중 에러 발생: {str(e)}")


# 🌟 [API 1] 자기소개 에디터용 이미지 업로드 API
@router.post("/api/upload/image")
async def upload_image(file: UploadFile = File(...)):
    print(f"📥 [이미지 업로드 요청] 파일명: {file.filename}")
    file_url = await upload_to_azure(file)
    print(f"✅ [이미지 업로드 완료] URL: {file_url}")
    return {"url": file_url}


# 🌟 [API 2] 호스트 등록/프로필용 이력서 파일 첨부 API
@router.post("/api/upload/file")
async def upload_file(file: UploadFile = File(...)):
    print(f"📥 [파일 업로드 요청] 파일명: {file.filename}")
    file_url = await upload_to_azure(file)
    print(f"✅ [파일 업로드 완료] URL: {file_url}")
    return {"url": file_url}