#!/bin/bash

# Maimbot 一键安装脚本 by Cookie987
# 适用于Debian系
# 请小心使用任何一键脚本！

# 如无法访问GitHub请修改此处镜像地址
GITHUB_REPO="https://github.com/SengokuCola/MaiMBot.git"

# 颜色输出
GREEN="\e[32m"
RED="\e[31m"
RESET="\e[0m"

# 需要的基本软件包
REQUIRED_PACKAGES=("git" "sudo" "python3" "python3-venv" "python3-pip")

# 默认项目目录
DEFAULT_INSTALL_DIR="/opt/maimbot"

# 服务名称
SERVICE_NAME="maimbot"

# 1/6: 检测是否安装 whiptail
if ! command -v whiptail &>/dev/null; then
    echo -e "${RED}[1/6] whiptail 未安装，正在安装...${RESET}"
    apt update && apt install -y whiptail
fi

get_os_info() {
    if command -v lsb_release &>/dev/null; then
        OS_INFO=$(lsb_release -d | cut -f2)
    elif [[ -f /etc/os-release ]]; then
        OS_INFO=$(grep "^PRETTY_NAME=" /etc/os-release | cut -d '"' -f2)
    else
        OS_INFO="Unknown OS"
    fi
    echo "$OS_INFO"
}

check_system() {
    OS_NAME=$(get_os_info)
    whiptail --title "⚙️ [2/6] 检查系统" --yesno "本脚本仅支持Debian 12。\n当前系统为 $OS_NAME\n是否继续？" 10 60 || exit 1
}
# 3/6: 询问用户是否安装缺失的软件包
install_packages() {
    missing_packages=()
    for package in "${REQUIRED_PACKAGES[@]}"; do
        if ! dpkg -s "$package" &>/dev/null; then
            missing_packages+=("$package")
        fi
    done

    if [[ ${#missing_packages[@]} -gt 0 ]]; then
        whiptail --title "📦 [3/6] 软件包检查" --yesno "检测到以下软件包缺失（MongoDB除外）:\n${missing_packages[*]}\n\n是否要自动安装？" 12 60
        if [[ $? -eq 0 ]]; then
            break
        else
            whiptail --title "⚠️ 注意" --yesno "某些必要的软件包未安装，可能会影响运行！\n是否继续？" 10 60 || exit 1
        fi
    fi
}

# 4/6: Python 版本检查
check_python() {
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

    python3 -c "import sys; exit(0) if sys.version_info >= (3,9) else exit(1)"
    if [[ $? -ne 0 ]]; then
        whiptail --title "⚠️ [4/6] Python 版本过低" --msgbox "检测到 Python 版本为 $PYTHON_VERSION，需要 3.9 或以上！\n请升级 Python 后重新运行本脚本。" 10 60
        exit 1
    fi
}

# 5/6: 选择分支
choose_branch() {
    BRANCH=$(whiptail --title "🔀 [5/6] 选择 Maimbot 分支" --menu "请选择要安装的 Maimbot 分支：" 15 60 2 \
        "main" "稳定版本（推荐）" \
        "debug" "开发版本（可能不稳定）" 3>&1 1>&2 2>&3)

    if [[ -z "$BRANCH" ]]; then
        BRANCH="main"
        whiptail --title "🔀 默认选择" --msgbox "未选择分支，默认安装稳定版本（main）" 10 60
    fi
}

# 6/6: 选择安装路径
choose_install_dir() {
    INSTALL_DIR=$(whiptail --title "📂 [6/6] 选择安装路径" --inputbox "请输入 Maimbot 的安装目录：" 10 60 "$DEFAULT_INSTALL_DIR" 3>&1 1>&2 2>&3)

    if [[ -z "$INSTALL_DIR" ]]; then
        whiptail --title "⚠️ 取消输入" --yesno "未输入安装路径，是否退出安装？" 10 60
        if [[ $? -ne 0 ]]; then
            INSTALL_DIR="$DEFAULT_INSTALL_DIR"
        else
            exit 1
        fi
    fi
}

# 显示确认界面
confirm_install() {
    local confirm_message="请确认以下更改:\n\n"

    if [[ ${#missing_packages[@]} -gt 0 ]]; then
        confirm_message+="📦 安装缺失的依赖项: ${missing_packages[*]}\n"
    else
        confirm_message+="✅ 所有依赖项已安装，无需额外安装\n"
    fi

    confirm_message+="📂 安装目录: $INSTALL_DIR\n"
    confirm_message+="🔀 分支: $BRANCH\n"

    if dpkg -s mongodb-org &>/dev/null; then
        confirm_message+="✅ MongoDB 已安装\n"
    else
        confirm_message+="⚠️ MongoDB 可能未安装（请参阅官方文档安装）\n"
    fi

    confirm_message+="🛠️ 添加 Maimbot 作为系统服务 ($SERVICE_NAME.service)\n"

    confirm_message+="\n\n注意：本脚本使用GitHub，如无法访问请手动修改仓库地址。"
    whiptail --title "🔧 安装确认" --yesno "$confirm_message\n\n是否继续安装？" 15 60
    if [[ $? -ne 0 ]]; then
        whiptail --title "🚫 取消安装" --msgbox "安装已取消。" 10 60
        exit 1
    fi
}

# 运行安装步骤
check_system
install_packages
check_python
choose_branch
choose_install_dir
confirm_install

# 开始安装
whiptail --title "🚀 开始安装" --msgbox "所有环境检查完毕，即将开始安装 Maimbot！" 10 60

echo -e "${GREEN}安装依赖项...${RESET}"

apt update && apt install -y "${missing_packages[@]}"

echo -e "${GREEN}创建 Python 虚拟环境...${RESET}"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR" || exit
python3 -m venv venv
source venv/bin/activate

echo -e "${GREEN}克隆仓库...${RESET}"
# 安装 Maimbot
mkdir -p "$INSTALL_DIR/repo"
cd "$INSTALL_DIR/repo" || exit 1
git clone -b "$BRANCH" $GITHUB_REPO .

echo -e "${GREEN}安装 Python 依赖...${RESET}"
pip install -r requirements.txt

echo -e "${GREEN}设置服务...${RESET}"
# 设置 Maimbot 服务
cat <<EOF | tee /etc/systemd/system/$SERVICE_NAME.service
[Unit]
Description=MaiMbot 麦麦
After=network.target mongod.service

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR/repo/
ExecStart=$INSTALL_DIR/venv/bin/python3 bot.py
ExecStop=/bin/kill -2 $MAINPID
Restart=always
RestartSec=10s

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable maimbot
systemctl start maimbot

whiptail --title "🎉 安装完成" --msgbox "Maimbot 安装完成！\n已经启动MaimBot服务。\n\n安装路径: $INSTALL_DIR\n分支: $BRANCH" 12 60
