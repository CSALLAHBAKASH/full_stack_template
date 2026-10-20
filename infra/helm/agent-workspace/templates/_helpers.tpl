{{- define "agent-workspace.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "agent-workspace.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "agent-workspace.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "agent-workspace.labels" -}}
app.kubernetes.io/name: {{ include "agent-workspace.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end }}

{{- define "agent-workspace.backendLabels" -}}
{{ include "agent-workspace.labels" . }}
app.kubernetes.io/component: backend
{{- end }}

{{- define "agent-workspace.frontendLabels" -}}
{{ include "agent-workspace.labels" . }}
app.kubernetes.io/component: frontend
{{- end }}
