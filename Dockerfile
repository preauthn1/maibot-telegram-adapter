FROM nonebot/nb-cli:latest
WORKDIR /
RUN apt update && apt install -y git
RUN git clone https://github.com/jiajiu123/MaiMBot
WORKDIR /MaiMBot
RUN mkdir config
RUN mv /MaiMBot/env.example /MaiMBot/config/.env \
&& mv /MaiMBot/src/plugins/chat/bot_config_toml /MaiMBot/config/bot_config.toml
RUN ln -s /MaiMBot/config/.env /MaiMBot/.env  \
&& ln -s /MaiMBot/config/bot_config.toml /MaiMBot/src/plugins/chat/bot_config.toml
RUN pip install -r requirements.txt
VOLUME [ "/MaiMBot/config" ]
EXPOSE 8080
ENTRYPOINT [ "nb","run" ]