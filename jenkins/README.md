# Local Jenkins (CI for the Data Platform)

A ready-to-run Jenkins controller for executing the repo's [`Jenkinsfile`](../Jenkinsfile).
Jenkins handles **CI** (lint, test, security scan, build & push images); **CD** stays
with ArgoCD — the pipeline only bumps an image tag in the GitOps repo, and ArgoCD
reconciles the cluster. This mirrors the GitHub Actions workflow so you can compare both.

## 1. Start Jenkins

```bash
docker compose -f jenkins/docker-compose.yml up -d --build
```

Open http://localhost:8088. Get the initial admin password:

```bash
docker exec data-platform-jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

Complete setup (the plugins from `plugins.txt` are pre-installed — you can skip the
suggested-plugins step) and create your admin user.

## 2. Add credentials

In **Manage Jenkins → Credentials → System → Global**, add two
*Username with password* credentials:

| ID                    | Used for                              | Username           | Password            |
| --------------------- | ------------------------------------- | ------------------ | ------------------- |
| `registry-credentials`| Push images to GHCR                   | your GitHub user   | a GHCR PAT (`write:packages`) |
| `gitops-credentials`  | Push the image-tag bump to the GitOps repo | your GitHub user | a repo-scoped PAT   |

## 3. Create the pipeline job

**New Item → Pipeline**, then under *Pipeline*:

- Definition: **Pipeline script from SCM**
- SCM: **Git**, Repository URL: `https://github.com/alokshukla92/data-platform.git`
- Branch: `*/main`
- Script Path: `Jenkinsfile`

Save and **Build Now**.

## What each stage does

1. **Lint & type-check** — `ruff check`, `ruff format --check`, `mypy` (advisory)
2. **Unit tests** — `pytest -m "not integration"` with coverage
3. **Security scan** — `bandit`, `pip-audit`
4. **Frontend build** — `npm install && npm run lint && npm run build`
5. **Build & push images** *(main only)* — app + frontend images to GHCR
6. **Promote (GitOps)** *(main only)* — bump the image tag in `data-platform-gitops`

Stages 1–4 run inside throwaway `python:3.12` / `node:20` containers via the Docker
Pipeline plugin; stages 5–6 use the host Docker socket mounted into the controller.

## Notes / hardening

- Running the controller as `root` with the Docker socket mounted is convenient for
  local use but is effectively host access. In a real deployment use an ephemeral agent
  (Kubernetes plugin) and a rootless/Kaniko build, and scope credentials per-job.
- The **Promote** stage's `sed` path (`environments/staging/values.yaml`) should match
  your GitOps repo layout; it no-ops safely if the path isn't found.
