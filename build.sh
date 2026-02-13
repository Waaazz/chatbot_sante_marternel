#!/usr/bin/env bash
# Script de build pour Render
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt
python -m spacy download fr_core_news_sm
