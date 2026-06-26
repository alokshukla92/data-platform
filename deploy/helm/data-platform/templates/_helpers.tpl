{{/* Common name + label helpers */}}
{{- define "dp.fullname" -}}
{{- printf "%s-%s" .Release.Name .name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "dp.labels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/part-of: data-platform
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .root.Chart.Name .root.Chart.Version }}
{{- end -}}

{{- define "dp.selectorLabels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{- define "dp.image" -}}
{{ .Values.global.imageRegistry }}:{{ .Values.global.imageTag }}
{{- end -}}

{{/* Standard env: ConfigMap (non-secret) + Secret (sensitive) */}}
{{- define "dp.env" -}}
envFrom:
  - configMapRef:
      name: {{ .Release.Name }}-config
  - secretRef:
      name: {{ .Release.Name }}-secrets
env:
  - name: SERVICE_NAME
    value: {{ .name | quote }}
  - name: ENVIRONMENT
    value: {{ .Values.global.environment | quote }}
{{- end -}}

{{/* HTTP probes shared by all FastAPI services */}}
{{- define "dp.probes" -}}
livenessProbe:
  httpGet: { path: /health/live, port: http }
  initialDelaySeconds: 10
  periodSeconds: 15
  failureThreshold: 3
readinessProbe:
  httpGet: { path: /health/ready, port: http }
  initialDelaySeconds: 5
  periodSeconds: 10
  failureThreshold: 3
startupProbe:
  httpGet: { path: /health/startup, port: http }
  failureThreshold: 30
  periodSeconds: 5
{{- end -}}
