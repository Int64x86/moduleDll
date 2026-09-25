@echo off

REM === CA ===
openssl genrsa -out ca.key 4096
openssl req -x509 -new -key ca.key -sha256 -days 3650 -out ca.crt -subj "/CN=Test CA"

REM === SERVER ===
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -subj "/CN=localhost"

echo extendedKeyUsage=serverAuth> server.ext
echo subjectAltName=DNS:localhost,IP:127.0.0.1>> server.ext

openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365 -sha256 -extfile server.ext

REM === CLIENT ===
openssl genrsa -out client.key 2048
openssl req -new -key client.key -out client.csr -subj "/CN=Test Client"

echo extendedKeyUsage=clientAuth> client.ext

openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days 365 -sha256 -extfile client.ext

REM === CLEANUP ===
del server.csr
del client.csr
del server.ext
del client.ext
del ca.srl

pause