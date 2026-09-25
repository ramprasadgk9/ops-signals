{{- define "ops-signals.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ops-signals.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "ops-signals.labels" -}}
app.kubernetes.io/name: {{ include "ops-signals.name" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* OPS_SIGNALS_API_TOKEN from security.apiTokenSecret; renders nothing when no Secret is named. */}}
{{- define "ops-signals.apiTokenEnv" -}}
{{- with .Values.security.apiTokenSecret.name }}
- name: OPS_SIGNALS_API_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ . }}
      key: {{ $.Values.security.apiTokenSecret.key }}
{{- end }}
{{- end }}
