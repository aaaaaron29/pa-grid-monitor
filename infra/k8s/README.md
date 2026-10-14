# Kubernetes manifests

Plain manifests, no Helm/Kustomize (Architecture.md Section 8's explicit choice). Apply
order doesn't matter beyond the general advice below: every Deployment and the migrate Job
are written to crash-loop and retry rather than depend on apply order, the standard K8s
pattern, not Docker Compose's `depends_on`.

## Current state (2026-10-14)

Written and YAML-syntax-validated (every file parses, the embedded dashboard JSON inside
`08-grafana.yaml` round-trips back to valid JSON). **Not yet applied to a real cluster.**
Same honest caveat `docker-compose.yml` had before CI actually proved it: careful on paper
is not the same as proven. Two real things are still missing before that proof is possible:

1. **No images are published yet.** Every manifest here references
   `ghcr.io/aaaaaron29/pa-grid-monitor-{ingestion,eia-inference,pjm-inference}:latest`,
   which doesn't exist as a real pushable image yet, only as local Dockerfiles. A CI job to
   build and push these on merge to `main` is the next piece of work, then a `kind`-based CI
   job (mirroring `compose-smoke-test`'s approach) to actually apply these manifests against
   a real, disposable Kubernetes cluster and confirm everything comes up.
2. **The PJM artifacts PVC starts empty.** See `06-inference.yaml`'s comment for the manual
   `kubectl cp` steps required after `pjm-inference`'s pod exists.

## Applying this for real

```
kubectl apply -f infra/k8s/
```

Before that works end to end, also:
- Populate the `pjm-artifacts` PVC (see `06-inference.yaml`).
- Install cert-manager if you want the Ingress's automatic TLS to actually issue a
  certificate (`09-ingress.yaml`'s header comment has the real prerequisites and what's
  still a placeholder: the contact email and the subdomain).
- For **local** testing (kind/k3d) rather than the real Oracle deploy: images need to be
  either pulled from a real registry (once the publish CI job exists) or built locally and
  loaded into the test cluster directly (`kind load docker-image`), since a local cluster
  can't reach a registry that doesn't have anything pushed to it yet.

## Differences worth knowing vs. `docker-compose.yml`

- **Images are pulled, not built.** Compose's `build:` directive doesn't exist in
  Kubernetes; every manifest here references a pre-built registry image.
- **Env vars split across a Secret and a ConfigMap** (`01-secrets.yaml`) instead of
  Compose's single `.env` file + `x-app-env` anchor. `POSTGRES_DSN` lives in the Secret
  (it embeds the password) even though most of its pieces aren't secret on their own,
  since `common/config.py`'s `Settings` only reads one `POSTGRES_DSN` string, not separate
  host/user/password fields.
- **PJM's artifact is a PersistentVolumeClaim**, populated manually via `kubectl cp`,
  instead of Compose's simple host bind mount (`./artifacts:/app/artifacts:ro`) -- there's
  no host filesystem to bind-mount from once this runs on a real cluster, and no automated
  artifact-publishing pipeline yet (would need its own registry/object-storage story,
  explicitly out of scope for this phase).
- **Grafana's provisioning config is two ConfigMaps**, generated from the exact same files
  `infra/grafana/provisioning/` already uses for Compose (see `08-grafana.yaml`'s own
  header), not a bind mount of that directory. Regenerate by re-running the embedding
  script if those source files change; there's no live sync between the two.
