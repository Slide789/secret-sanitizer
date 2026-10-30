#!/bin/bash
export AWS_ACCESS_KEY_ID=AKIAI59BWVDTB1TV8TLK
export AWS_SECRET_ACCESS_KEY=eVx3nDJcrqmaaFpt8pJ82qpEmqCDOmTPAHUySAOM
export GITHUB_TOKEN=ghp_LvAeNRyN996pJD30rNGNe0za3qYdqUcgQ0Vn
export API_TOKEN="yYY92NXGq4xf9fLdjaIBGJjUm74BKsCb"
export DB_PASSWORD='Fake-Pa55w0rd!'
export PATH=/usr/local/bin:/usr/bin:/bin
export LANG=de_DE.UTF-8
mysql -u root -pMyFakeSql99 -h 192.168.178.23 prod < dump.sql
curl -u fakeuser:curlFake#77 https://api.example.com/v1/status
sshpass -p 'Fake-Pa55w0rd!' ssh jdoe@db01.intra.fake-firma.local
docker run -p 8080:80 nginx
ssh -p 2222 backup@192.168.178.23
