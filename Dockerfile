FROM nonebot/nb-cli:latest
WORKDIR /
RUN apt update && apt install -y git
RUN git clone https://github.com/jiajiu123/MaiMBot
WORKDIR /MaiMBot
RUN mkdir config
RUN mv /app/env.example /app/config/.env \
&& mv /app/src/plugins/chat/bot_config_toml /app/config/bot_config.toml
RUN ln -s /app/config/.env /app/.env  \
&& ln -s /app/config/bot_config.toml /app/src/plugins/chat/bot_config.toml
RUN pip install -r requirements.txt
VOLUME [ "/app/config" ]
EXPOSE 8080
ENTRYPOINT [ "nb","run" ]