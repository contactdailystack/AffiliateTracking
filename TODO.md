
- [x] แก้ไข docker-compose.yml: ให้ service postgres และ redis อยู่ใน network เดียวกับ api/worker (mvp-network)
- [x] รีสตาร์ท stack (docker compose up -d หรือ restart containers ที่เกี่ยวข้อง)
- [x] ตรวจ DNS จากภายใน mvp-api: getent hosts postgres และ getent hosts redis
- [x] กด Load Projects ด้วย key เดิม (ตอนนี้ได้ 401 Invalid API key แล้ว ไม่ใช่ 500)
- [x] ตรวจ docker logs mvp-api ว่าไม่เกิด OperationalError/500 (ตอนนี้เป็น 401 Invalid API key)
- [ ] สรุป final RCA + ไฟล์ที่แก้ไข + วิธีทดสอบ
