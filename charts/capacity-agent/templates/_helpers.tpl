{{- define "ca.name" -}}capacity-agent{{- end -}}
{{- define "ca.fullname" -}}{{ .Release.Name | trunc 63 | trimSuffix "-" }}{{- end -}}
{{- define "ca.labels" -}}
app.kubernetes.io/name: {{ include "ca.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
{{- define "ca.selector" -}}
app.kubernetes.io/name: {{ include "ca.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
{{- define "ca.keySecret" -}}{{ .Values.encryption.existingSecret | default (printf "%s-encryption" (include "ca.fullname" .)) }}{{- end -}}
{{- define "ca.claim" -}}{{ .Values.persistence.existingClaim | default (printf "%s-data" (include "ca.fullname" .)) }}{{- end -}}
