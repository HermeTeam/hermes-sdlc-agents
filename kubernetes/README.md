# Kubernetes deployment

Этот каталог разворачивается из корня bundle, потому что root `kustomization.yaml` читает profile configs и SOUL из `profiles/`.

## 1. Подготовьте namespace и secrets

Kubernetes не читает Docker Compose `.env`: каждый Deployment получает runtime env из собственного Secret `hermes-<role>-env` через `envFrom`. Создайте эти Secrets отдельно, например из локальных `secrets/hermes-${role}.env` файлов, которые содержат Kubernetes keys such as `HERMES_MODEL_ID`, `HERMES_MODEL_BASE_URL`, `API_SERVER_KEY`, `API_SERVER_MODEL_NAME`, `GIT_PROVIDER_MCP_TOKEN`, and role-local orchestrator tokens. Repository clone Secret для builder больше не нужен. В Docker Compose role-specific tokens находятся в основном `.env` как `PLANNER_GITHUB_MCP_TOKEN`, `PROJECT_MANAGER_GITHUB_MCP_TOKEN`, `BUILDER_GITHUB_MCP_TOKEN` и т.д.; для Kubernetes перенесите соответствующее значение в secret key `GIT_PROVIDER_MCP_TOKEN` каждого `hermes-<role>-env` или подключите External Secrets с таким mapping.

Создайте Secrets:

```bash
kubectl apply -f kubernetes/namespace.yaml
for role in planner project-manager builder reviewer release incident learning; do
  kubectl -n hermes-sdlc create secret generic "hermes-${role}-env" \
    --from-env-file="secrets/hermes-${role}.env" \
    --dry-run=client -o yaml | kubectl apply -f -
done
```

Для production используйте External Secrets Operator/SOPS/OpenBao вместо ручных Secrets.

## 2. Pin images

Измените root `kustomization.yaml`: замените `newTag: latest` на проверенный tag или используйте `digest:`. Также pin-ьте `alpine/git` init image в `kubernetes/hermes-builder.yaml`.

## 3. Network policy prerequisites

По умолчанию egress разрешён только DNS и Pods в namespace `platform` с labels:

- `app.kubernetes.io/name=llm-gateway` на TCP 4000/443;
- `app.kubernetes.io/name=git-provider-mcp` на TCP 8080/443.

Hermes Pods в MVP требуют egress к GitHub/GitLab provider API/MCP endpoint. Прямой доступ к публичным package registries по умолчанию закрыт.

Ingress к Hermes API разрешён только из namespace с label `hermes-sdlc-client=true`. Адаптируйте policy до deploy, если gateways внешние или используют другие ports/labels.

```bash
kubectl label namespace your-orchestrator hermes-sdlc-client=true
```

## 4. Render, review, apply

```bash
kubectl kustomize . > /tmp/hermes-sdlc.rendered.yaml
kubectl apply --server-side -f /tmp/hermes-sdlc.rendered.yaml
kubectl -n hermes-sdlc rollout status deployment --all --timeout=10m
```

Каждый Deployment использует `strategy: Recreate`, отдельный PVC и `automountServiceAccountToken: false`. У самих Hermes Pods нет Kubernetes RBAC. Release/incident mutations выполняются только отдельными узкими integrations со своими service accounts.

## 5. Verify

```bash
kubectl -n hermes-sdlc get pods,svc,pvc
kubectl -n hermes-sdlc port-forward svc/hermes-planner 18642:8642
curl --fail http://127.0.0.1:18642/health
```

После liveness проведите authenticated positive/negative canaries из основного README и проверьте provider MCP/upstream audit.
