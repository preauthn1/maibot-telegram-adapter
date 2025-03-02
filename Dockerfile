FROM nonebot/nb-cli:latest
WORKDIR /
COPY . /MaiMBot/
WORKDIR /MaiMBot
RUN pip install --upgrade -r requirements.txt
VOLUME [ "/MaiMBot/config" ]
EXPOSE 8080
ENTRYPOINT [ "nb","run" ]
