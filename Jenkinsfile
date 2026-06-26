// Declarative Jenkins pipeline — an alternative CI to the GitHub Actions workflow
// (.github/workflows/ci.yml). Same stages: lint, type-check, test, security scan,
// build + push images, then bump the image tag in the GitOps repo so ArgoCD
// reconciles the change (Jenkins does CI; ArgoCD does CD — Jenkins never kubectl-applies).
//
// Requirements on the Jenkins controller/agent (see jenkins/ for a ready-to-run setup):
//   * Docker CLI + access to the Docker daemon (socket mounted)
//   * Credentials:
//       - 'registry-credentials'  (username/password) for the container registry
//       - 'gitops-credentials'    (username/password or token) to push to the GitOps repo
//   * Plugins: Docker Pipeline, Git, Credentials Binding

pipeline {
  agent any

  options {
    timestamps()
    timeout(time: 45, unit: 'MINUTES')
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '20'))
  }

  environment {
    REGISTRY        = 'ghcr.io'
    IMAGE_OWNER     = 'alokshukla92'
    APP_IMAGE       = "${REGISTRY}/${IMAGE_OWNER}/data-platform"
    FRONTEND_IMAGE  = "${REGISTRY}/${IMAGE_OWNER}/data-platform-frontend"
    IMAGE_TAG       = "${env.GIT_COMMIT?.take(12) ?: env.BUILD_NUMBER}"
    GITOPS_REPO     = "https://github.com/${IMAGE_OWNER}/data-platform-gitops.git"
    PY_IMAGE        = 'python:3.12-slim'
    NODE_IMAGE      = 'node:20-alpine'
  }

  stages {
    stage('Lint & type-check') {
      agent { docker { image "${PY_IMAGE}"; reuseNode true } }
      steps {
        sh '''
          pip install --no-cache-dir -e ".[dev]"
          ruff check .
          ruff format --check .
          mypy libs services workers || true   # advisory until fully typed
        '''
      }
    }

    stage('Unit tests') {
      agent { docker { image "${PY_IMAGE}"; reuseNode true } }
      steps {
        sh '''
          pip install --no-cache-dir -e ".[dev]"
          pytest -m "not integration" --cov --cov-report=xml --cov-report=term-missing
        '''
      }
      post {
        always { archiveArtifacts artifacts: 'coverage.xml', allowEmptyArchive: true }
      }
    }

    stage('Security scan') {
      agent { docker { image "${PY_IMAGE}"; reuseNode true } }
      steps {
        sh '''
          pip install --no-cache-dir bandit pip-audit
          bandit -r libs services workers -ll
          pip-audit --strict || true   # advisory; do not fail build on transitive CVEs
        '''
      }
    }

    stage('Frontend build') {
      agent { docker { image "${NODE_IMAGE}"; reuseNode true } }
      steps {
        dir('frontend') {
          sh '''
            npm install
            npm run lint
            npm run build
          '''
        }
      }
    }

    stage('Build & push images') {
      when { branch 'main' }
      steps {
        script {
          docker.withRegistry("https://${REGISTRY}", 'registry-credentials') {
            def app = docker.build("${APP_IMAGE}:${IMAGE_TAG}",
                                   "--build-arg PREFETCH_MODEL=false -f docker/Dockerfile .")
            app.push()
            app.push('latest')

            def fe = docker.build("${FRONTEND_IMAGE}:${IMAGE_TAG}", "frontend")
            fe.push()
            fe.push('latest')
          }
        }
      }
    }

    stage('Promote (GitOps)') {
      when { branch 'main' }
      steps {
        withCredentials([usernamePassword(credentialsId: 'gitops-credentials',
                                           usernameVariable: 'GIT_USER',
                                           passwordVariable: 'GIT_TOKEN')]) {
          sh '''
            rm -rf gitops && git clone "https://${GIT_USER}:${GIT_TOKEN}@github.com/'"${IMAGE_OWNER}"'/data-platform-gitops.git" gitops
            cd gitops
            # Bump the image tag the staging/prod ApplicationSet renders from.
            # Adjust the path to match your GitOps layout (see data-platform-gitops repo).
            if [ -f environments/staging/values.yaml ]; then
              sed -i "s|imageTag:.*|imageTag: ${IMAGE_TAG}|" environments/staging/values.yaml
              git config user.email "ci@data-platform.local"
              git config user.name  "jenkins-ci"
              git add -A
              git commit -m "ci: bump image tag to ${IMAGE_TAG}" || echo "no changes to commit"
              git push origin HEAD:main
            else
              echo "GitOps values path not found; skipping promotion (configure to match your repo)."
            fi
          '''
        }
      }
    }
  }

  post {
    success { echo "CI succeeded — images ${APP_IMAGE}:${IMAGE_TAG} and ${FRONTEND_IMAGE}:${IMAGE_TAG}" }
    failure { echo 'CI failed — see stage logs above.' }
  }
}
