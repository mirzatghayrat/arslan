"""Localized, bounded explanations of recognized provider failures."""
from server.services.runtime_messages import normalize

MESSAGES = {
    "en": {
        "not_configured": "No model connection is configured. Choose a provider and model in connection settings before sending.",
        "context": "This conversation exceeds the model's context limit. Start a new conversation or choose a model with a larger context window.",
        "transport": "The connection to the provider failed or was interrupted. Check the network, proxy, or VPN. This error alone does not establish an API key problem or whether the provider processed the request.",
        "key_limit": "This API key has reached its usage limit; the account may still have a balance. Review the key's limit in the provider's dashboard before deciding what to change.",
        "region": "The provider reports that this model is unavailable in your region. This is different from an invalid key or insufficient balance. Choose a model available in your region.",
        "payment": "The provider reports insufficient account balance or credits. Review billing and request limits in the provider's dashboard before retrying.",
        "auth": "The provider rejected this API key. Check whether it is valid, expired, or missing permissions in the connection settings.",
        "rate": "The provider is rate-limiting requests. Wait before retrying, or choose another available model.",
        "key_required": "The server rejected an unauthenticated request (HTTP {status}). Check whether this connection requires an API key and the necessary permissions.",
        "connection_failed": "The model connection test failed without a detailed error. Check the connection settings and try again.",
    },
    "zh": {
        "not_configured": "尚未配置模型连接。请先在连接设置中选择服务商和模型，再发送消息。",
        "context": "这轮对话太长，超过了模型的上下文上限。请新建对话，或选择上下文更大的模型。",
        "transport": "没能连上服务商，或连接中途断开。请检查网络、代理或 VPN。仅凭这个错误，不能确定是 API key 的问题，也不能确定服务商是否已处理请求。",
        "key_limit": "这把 API key 已达到用量上限，账户里可能仍有余额。请到服务商后台检查这把 key 的限额，再决定如何调整。",
        "region": "服务商报告这个模型在你所在的地区不可用。这与 key 无效或余额不足不同，请选择所在地区可用的模型。",
        "payment": "服务商报告账户余额不足或可用额度不足。请先在服务商后台核对账单和请求限额，再决定是否重试。",
        "auth": "服务商拒绝了这把 API key。请在连接设置中检查 key 是否有效、已过期或缺少所需权限。",
        "rate": "服务商正在限流。请稍后再试，或选择其他可用模型。",
        "key_required": "服务器拒绝了未认证的请求（HTTP {status}）。请确认这个连接是否要求 API key，以及所需权限。",
        "connection_failed": "模型连接测试失败，未返回详细原因。请检查连接设置后重试。",
    },
    "ja": {
        "not_configured": "モデル接続が設定されていません。送信前に接続設定でプロバイダーとモデルを選択してください。",
        "context": "この会話はモデルのコンテキスト上限を超えています。新しい会話を始めるか、上限の大きいモデルを選んでください。",
        "transport": "プロバイダーへの接続に失敗したか、接続が中断されました。ネットワーク、プロキシ、VPN を確認してください。このエラーだけでは、API キーの問題かどうかや、リクエストが処理されたかどうかは判断できません。",
        "key_limit": "この API キーは使用量の上限に達しています。アカウントには残高がある可能性があります。変更する前に、プロバイダーの管理画面でキーの上限を確認してください。",
        "region": "プロバイダーによると、このモデルは現在の地域では利用できません。キーの無効や残高不足とは異なります。地域で利用可能なモデルを選んでください。",
        "payment": "プロバイダーが残高または利用可能なクレジットの不足を報告しています。再試行する前に、管理画面で請求状況とリクエスト制限を確認してください。",
        "auth": "プロバイダーが API キーを拒否しました。接続設定でキーの有効性、有効期限、必要な権限を確認してください。",
        "rate": "プロバイダーがリクエストを制限しています。時間を置いて再試行するか、別の利用可能なモデルを選んでください。",
        "key_required": "サーバーが未認証のリクエストを拒否しました（HTTP {status}）。この接続に API キーと必要な権限が求められるか確認してください。",
        "connection_failed": "モデルの接続テストに失敗しましたが、詳細な原因は返されませんでした。接続設定を確認して再試行してください。",
    },
    "es": {
        "not_configured": "No hay ninguna conexión de modelo configurada. Elige un proveedor y un modelo en los ajustes de conexión antes de enviar.",
        "context": "Esta conversación supera el límite de contexto del modelo. Inicia una conversación nueva o elige un modelo con una ventana de contexto mayor.",
        "transport": "La conexión con el proveedor falló o se interrumpió. Comprueba la red, el proxy o la VPN. Este error por sí solo no confirma un problema con la clave API ni si el proveedor procesó la solicitud.",
        "key_limit": "Esta clave API ha alcanzado su límite de uso; puede que la cuenta aún tenga saldo. Revisa el límite de la clave en el panel del proveedor antes de decidir qué cambiar.",
        "region": "El proveedor indica que este modelo no está disponible en tu región. No es lo mismo que una clave no válida o un saldo insuficiente. Elige un modelo disponible en tu región.",
        "payment": "El proveedor indica que el saldo o los créditos son insuficientes. Revisa la facturación y los límites de solicitudes en su panel antes de volver a intentarlo.",
        "auth": "El proveedor rechazó esta clave API. Comprueba su validez, caducidad y permisos en los ajustes de conexión.",
        "rate": "El proveedor está limitando las solicitudes. Espera antes de reintentarlo o elige otro modelo disponible.",
        "key_required": "El servidor rechazó una solicitud sin autenticar (HTTP {status}). Comprueba si esta conexión requiere una clave API y los permisos necesarios.",
        "connection_failed": "La prueba de conexión del modelo falló sin indicar un error detallado. Revisa los ajustes de conexión y vuelve a intentarlo.",
    },
    "de": {
        "not_configured": "Es ist keine Modellverbindung eingerichtet. Wähle vor dem Senden in den Verbindungseinstellungen einen Anbieter und ein Modell.",
        "context": "Diese Unterhaltung überschreitet das Kontextlimit des Modells. Beginne eine neue Unterhaltung oder wähle ein Modell mit einem größeren Kontextfenster.",
        "transport": "Die Verbindung zum Anbieter ist fehlgeschlagen oder wurde unterbrochen. Prüfe Netzwerk, Proxy oder VPN. Dieser Fehler allein belegt weder ein Problem mit dem API-Schlüssel noch, ob der Anbieter die Anfrage verarbeitet hat.",
        "key_limit": "Dieser API-Schlüssel hat sein Nutzungslimit erreicht; das Konto kann noch Guthaben haben. Prüfe das Schlüssellimit im Anbieter-Dashboard, bevor du Änderungen vornimmst.",
        "region": "Laut Anbieter ist dieses Modell in deiner Region nicht verfügbar. Das ist etwas anderes als ein ungültiger Schlüssel oder fehlendes Guthaben. Wähle ein in deiner Region verfügbares Modell.",
        "payment": "Der Anbieter meldet unzureichendes Guthaben. Prüfe Abrechnung und Anfragelimits im Anbieter-Dashboard, bevor du es erneut versuchst.",
        "auth": "Der Anbieter hat diesen API-Schlüssel abgelehnt. Prüfe in den Verbindungseinstellungen Gültigkeit, Ablaufdatum und benötigte Berechtigungen.",
        "rate": "Der Anbieter begrenzt die Anfragerate. Warte vor einem erneuten Versuch oder wähle ein anderes verfügbares Modell.",
        "key_required": "Der Server hat eine nicht authentifizierte Anfrage abgelehnt (HTTP {status}). Prüfe, ob diese Verbindung einen API-Schlüssel und die nötigen Berechtigungen erfordert.",
        "connection_failed": "Der Modell-Verbindungstest ist ohne detaillierte Fehlermeldung fehlgeschlagen. Prüfe die Verbindungseinstellungen und versuche es erneut.",
    },
    "fr": {
        "not_configured": "Aucune connexion à un modèle n’est configurée. Choisis un fournisseur et un modèle dans les paramètres de connexion avant l’envoi.",
        "context": "Cette conversation dépasse la limite de contexte du modèle. Ouvre une nouvelle conversation ou choisis un modèle disposant d’une fenêtre de contexte plus grande.",
        "transport": "La connexion au fournisseur a échoué ou a été interrompue. Vérifie le réseau, le proxy ou le VPN. Cette erreur seule ne permet pas de conclure à un problème de clé API ni de savoir si la requête a été traitée.",
        "key_limit": "Cette clé API a atteint sa limite d’utilisation ; le compte peut encore avoir du crédit. Vérifie la limite de la clé dans le tableau de bord du fournisseur avant de décider quoi modifier.",
        "region": "Le fournisseur indique que ce modèle n’est pas disponible dans ta région. Cela diffère d’une clé invalide ou d’un solde insuffisant. Choisis un modèle disponible dans ta région.",
        "payment": "Le fournisseur indique un solde ou des crédits insuffisants. Vérifie la facturation et les limites des requêtes dans son tableau de bord avant de réessayer.",
        "auth": "Le fournisseur a refusé cette clé API. Vérifie sa validité, son expiration et les autorisations nécessaires dans les paramètres de connexion.",
        "rate": "Le fournisseur limite la fréquence des requêtes. Attends avant de réessayer ou choisis un autre modèle disponible.",
        "key_required": "Le serveur a refusé une requête non authentifiée (HTTP {status}). Vérifie si cette connexion nécessite une clé API et les autorisations requises.",
        "connection_failed": "Le test de connexion au modèle a échoué sans erreur détaillée. Vérifie les paramètres de connexion et réessaie.",
    },
}


class ModelNotConfiguredError(ValueError):
    """Typed product error; never infer this condition from provider prose."""


def render(key, locale, **values):
    return MESSAGES[normalize(locale)][key].format(**values)
