#!/usr/bin/env bash
# Докачивает фирменные шрифты. Запускать один раз после клонирования.
# Музыку и логотип кладём руками — см. README.
set -euo pipefail

cd "$(dirname "$0")/.."
FONTS=assets/fonts
mkdir -p "$FONTS"

get() {  # get <url> <файл>
  if [ -s "$FONTS/$2" ]; then echo "  уже есть: $2"; return; fi
  echo "  качаю: $2"
  curl -fsSL "$1" -o "$FONTS/$2" || echo "  !! не скачался: $2"
}

echo "Шрифты:"
BASE=https://raw.githubusercontent.com/google/fonts/main
get "$BASE/ofl/oswald/Oswald%5Bwght%5D.ttf"        Oswald-Variable.ttf
get "$BASE/ofl/golostext/GolosText%5Bwght%5D.ttf"  GolosText-Variable.ttf
get "$BASE/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf" JetBrainsMono-Variable.ttf

echo
echo "Готово. Что доложить руками:"
echo "  assets/brand/logo.png   — логотип на прозрачном фоне, белый вариант, высота от 300 px"
echo "  assets/music/*.mp3      — 3-5 треков без авторских прав (Pixabay Music, Uppbeat)"
echo
echo "Без музыки ролики будут немыми, без логотипа подставится текстовый ARINASTROYS."
