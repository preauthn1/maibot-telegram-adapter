FROM nonebot/nb-cli:latest
WORKDIR /
COPY . /MaiMBot/
WORKDIR /MaiMBot
RUN mv config/env.example config/.env \
&& mv config/bot_config_toml config/bot_config.toml
RUN pip install --upgrade -r requirements.txt
VOLUME [ "/MaiMBot/config" ]
EXPOSE 8080
ENTRYPOINT [ "nb","run" ]