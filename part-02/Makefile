# Part 2 runbook as make targets (the README's commands; `make -n <target>` prints them).
# From the repository root: make -C part-02 help. Recipes source .env, so secrets bypass make.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

CLUSTER          := poc-part-02
NAMESPACE        := kong
OPERATOR_VERSION := 1.5.0-rapid.2.0
LOAD_ENV         := set -a; source ./.env; set +a;
TF               := terraform -chdir=terraform

.PHONY: help up down cluster cluster-down operator tf-init tf-plan tf-apply tf-destroy konnect-secret gateway gateway-down status test test-fail-closed lint

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-17s %s\n", $$1, $$2}'

up: cluster operator tf-apply konnect-secret gateway ## Everything, in order (Terraform asks before applying)

down: cluster-down ## Delete the cluster. The gateway stays in Konnect: `make tf-destroy` removes it

# --- Cluster (local stand-in for EKS) ---------------------------------------------------------

cluster: ## Create the kind cluster (localhost:8000 -> gateway)
	kind get clusters | grep -qx $(CLUSTER) || kind create cluster --config kind-config.yaml

cluster-down: ## Delete the kind cluster
	kind delete cluster --name $(CLUSTER)

operator: ## Install Kong Operator (Helm) and wait for its CRDs
	helm repo add kong https://charts.konghq.com --force-update
	helm upgrade --install kong-operator kong/kong-operator -n kong-system --create-namespace \
	  --version $(OPERATOR_VERSION) -f helm/operator-values.yaml --wait
	kubectl wait --for=condition=Established --timeout=120s \
	  crd/konnectaigateways.konnect.konghq.com crd/aigatewaydataplanes.aigateway.konghq.com

# --- Control plane and configuration (Terraform) ----------------------------------------------

tf-init: ## terraform init
	$(TF) init

tf-plan: tf-init ## terraform plan
	$(LOAD_ENV) $(TF) plan

tf-apply: tf-init ## terraform apply (shows the plan and asks first)
	$(LOAD_ENV) $(TF) apply

tf-destroy: ## terraform destroy: deletes the gateway and its config from Konnect
	$(LOAD_ENV) $(TF) destroy

# --- Data plane and PII service (Helm) --------------------------------------------------------

konnect-secret: ## Store the Konnect token in a Secret for the operator (idempotent)
	kubectl create namespace $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	$(LOAD_ENV) kubectl -n $(NAMESPACE) create secret generic konnect-token \
	  --from-literal=token="$$KONNECT_TOKEN" --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n $(NAMESPACE) label secret konnect-token --overwrite \
	  konghq.com/credential=konnect konghq.com/secret=true

gateway: ## Install the poc-ai-gateway chart (gatewayId from terraform output)
	helm upgrade --install poc-ai-gateway helm/poc-ai-gateway -n $(NAMESPACE) --create-namespace \
	  --set gatewayId="$$($(TF) output -raw gateway_id)"

gateway-down: ## Uninstall the chart (the gateway in Konnect is untouched)
	helm uninstall poc-ai-gateway -n $(NAMESPACE)

# The usage dashboard covers both gateways: `make -C shared dashboard`.

status: ## Operator resources, pods and the last data plane log lines
	kubectl -n $(NAMESPACE) get konnectaigateway,aigatewaydataplane,pods,svc
	kubectl -n $(NAMESPACE) logs -l gateway-operator.konghq.com/managed-by-name=ai-gateway-dp --tail=20 || true

# --- Checks -----------------------------------------------------------------------------------

test: ## Run the gateway test suite
	python3 test_gateway.py

test-fail-closed: ## Test suite plus the PII fail-closed check (scales the PII service to 0 and back)
	python3 test_gateway.py --fail-closed

lint: ## Static checks: terraform fmt/validate, helm lint/template (changes nothing)
	terraform -chdir=terraform fmt -check -recursive
	$(TF) init -backend=false -input=false >/dev/null
	$(TF) validate
	helm lint helm/poc-ai-gateway --set gatewayId=00000000-0000-0000-0000-000000000000
	helm template poc-ai-gateway helm/poc-ai-gateway -n $(NAMESPACE) \
	  --set gatewayId=00000000-0000-0000-0000-000000000000 >/dev/null
