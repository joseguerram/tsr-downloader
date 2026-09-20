# TSR Downloader — tareas comunes
# Funciona en Linux, macOS y Windows (vía Git Bash o WSL).

PYTHON := python
VENV   := .venv

ifeq ($(OS),Windows_NT)
VENV_BIN := $(VENV)/Scripts
PY       := $(VENV_BIN)/python.exe
else
VENV_BIN := $(VENV)/bin
PY       := $(VENV_BIN)/python
endif

.DEFAULT_GOAL := help

help: ## Muestra esta ayuda
	@echo "TSR Downloader — tareas disponibles:"
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  make %-10s %s\n", $$1, $$2}'

setup: ## Crea el entorno virtual, instala dependencias y genera config.json
	@echo "==> Entorno virtual: $(VENV)"
	$(PYTHON) -m venv $(VENV)
	@echo "==> Instalando dependencias..."
	$(PY) -m pip install --upgrade pip -q
	$(PY) -m pip install -r requirements.txt
	@echo "==> Configuración..."
	@if [ ! -f config.json ]; then \
		cp config.json.example config.json && \
		echo "    -> config.json generado desde config.json.example"; \
	else \
		echo "    -> config.json ya existe, sin cambios"; \
	fi
	@echo
	@echo "Instalación completa. Edita config.json con tu cuenta de TSR y ejecuta 'make run'."

run: ## Ejecuta la aplicación
	@if [ ! -f $(PY) ]; then \
		echo "Entorno no preparado. Ejecuta primero 'make setup'."; \
		exit 1; \
	fi
	$(PY) -m src.main

clean: ## Elimina el entorno virtual y archivos temporales (no toca config.json ni descargas)
	@echo "==> Eliminando $(VENV)..."
	rm -rf $(VENV)
	@echo "==> Eliminando cachés..."
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f logs.log
	@echo "Listo."