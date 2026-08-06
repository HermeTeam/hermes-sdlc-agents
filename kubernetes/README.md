# Kubernetes deployment

Этот каталог разворачивается из корня bundle, потому что root `kustomization.yaml` читает profile configs и SOUL из `profiles/`.

## 1. Подготовьте namespace и secrets

Создайте реальные env-файлы через `scripts/bootstrap.sh`, затем замените все `CHANGE_ME`. Repository clone Secret для builder больше не нужен: Hermes Pod использует только короткоживущий role-scoped `GIT_PROVIDER_MCP_TOKEN` для прямого GitHub/GitLab API/MCP endpoint.

Создайте Secrets:

```bash
kubectl apply -f kubernetes/namespace.yaml
for role in planner builder reviewer release incident learning; do
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
