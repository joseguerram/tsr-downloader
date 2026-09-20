# TSR Downloader — atajo opcional (solo conviene por comodidad).
# La única fuente de verdad es run.py: funciona sin make, solo con Python.
# En Windows nativo: usa Git Bash, WSL o directamente 'python run.py ...'.

PYTHON := python

.DEFAULT_GOAL := help

help: ## Muestra esta ayuda
	@$(PYTHON) run.py help

setup: ## Crea el entorno virtual, instala dependencias y genera config.json
	@$(PYTHON) run.py setup

run: ## Ejecuta la aplicación (setup automático si falta)
	@$(PYTHON) run.py run

clean: ## Elimina el entorno virtual y archivos temporales (no toca config.json ni descargas)
	@$(PYTHON) run.py clean