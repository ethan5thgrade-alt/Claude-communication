# agent-mesh Makefile
# Run `make help` (or just `make`) for the list of targets.

PYTHON       := python3.13
REPO_DIR     := $(shell pwd)
PLIST_NAME   := com.voidlabs.agent-mesh.plist
PLIST_SRC    := $(REPO_DIR)/$(PLIST_NAME)
PLIST_DEST   := $(HOME)/Library/LaunchAgents/$(PLIST_NAME)
LOG_DIR      := $(HOME)/Library/Logs/agent-mesh
LABEL        := com.voidlabs.agent-mesh

.PHONY: help dev test install-service uninstall-service restart-service tail-logs status

help:
	@echo "agent-mesh — available targets:"
	@echo ""
	@echo "  make dev                 Run the broker in the foreground"
	@echo "  make test                Run the pytest suite"
	@echo "  make install-service     Install + start the launchd service"
	@echo "  make uninstall-service   Stop + remove the launchd service"
	@echo "  make restart-service     Unload then load the launchd service"
	@echo "  make tail-logs           Tail the launchd stdout/stderr logs"
	@echo "  make status              Show launchctl status for the service"
	@echo ""
	@echo "Logs: $(LOG_DIR)/out.log  $(LOG_DIR)/err.log"

dev:
	$(PYTHON) -u broker.py

test:
	$(PYTHON) -m pytest tests/ -v

install-service:
	@mkdir -p $(LOG_DIR)
	@mkdir -p $(HOME)/Library/LaunchAgents
	@cp $(PLIST_SRC) $(PLIST_DEST)
	@echo "Copied plist to $(PLIST_DEST)"
	@launchctl unload $(PLIST_DEST) 2>/dev/null || true
	@launchctl load $(PLIST_DEST)
	@echo "Loaded $(LABEL). Current status:"
	@launchctl list | grep $(LABEL) || echo "(not yet listed — give it a sec, then run 'make status')"
	@echo ""
	@echo "Logs: $(LOG_DIR)/out.log  $(LOG_DIR)/err.log"

uninstall-service:
	@launchctl unload $(PLIST_DEST) 2>/dev/null || true
	@rm -f $(PLIST_DEST)
	@echo "Removed $(PLIST_DEST)"

restart-service:
	@launchctl unload $(PLIST_DEST) 2>/dev/null || true
	@launchctl load $(PLIST_DEST)
	@echo "Reloaded $(LABEL)."

tail-logs:
	@mkdir -p $(LOG_DIR)
	@touch $(LOG_DIR)/out.log $(LOG_DIR)/err.log
	tail -F $(LOG_DIR)/out.log $(LOG_DIR)/err.log

status:
	@launchctl list | grep $(LABEL) || echo "$(LABEL) not loaded"
