using System;

public class CPHInline
{
    const string RouterActionName = "Kinkajou Bridge";
    const string UserActionPrefix = "Kinkajou - ";

    public bool Execute()
    {
        if (!CPH.TryGetArg("event_name", out string eventName) ||
            string.IsNullOrWhiteSpace(eventName))
        {
            if (!CPH.TryGetArg("event_type", out string eventType) ||
                string.IsNullOrWhiteSpace(eventType))
            {
                CPH.LogWarn("Kinkajou Bridge: missing event_name / event_type");
                return false;
            }
            eventName = BuildUserActionName(eventType);
            CPH.SetArgument("event_name", eventName);
        }

        eventName = eventName.Trim();

        // Never recurse into the router itself.
        if (string.Equals(eventName, RouterActionName, StringComparison.OrdinalIgnoreCase))
        {
            CPH.LogWarn("Kinkajou Bridge: event_name points at the router action; ignoring");
            return false;
        }

        if (!eventName.StartsWith(UserActionPrefix, StringComparison.Ordinal))
        {
            CPH.LogWarn($"Kinkajou Bridge: unexpected event_name '{eventName}'");
            return false;
        }

        if (!CPH.ActionExists(eventName))
        {
            // User has not created a handler for this event — that is fine.
            CPH.LogDebug($"Kinkajou Bridge: no user action named '{eventName}'");
            return true;
        }

        // runImmediately: true keeps Bridge args on the stack for the user action.
        bool ran = CPH.RunAction(eventName, true);
        if (!ran)
        {
            CPH.LogWarn($"Kinkajou Bridge: failed to run '{eventName}'");
            return false;
        }

        return true;
    }

    static string BuildUserActionName(string eventType)
    {
        string[] parts = eventType
            .Replace('.', ' ')
            .Replace('_', ' ')
            .Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);

        for (int i = 0; i < parts.Length; i++)
        {
            string part = parts[i];
            if (part.Length == 0) continue;
            parts[i] = char.ToUpperInvariant(part[0])
                + (part.Length > 1 ? part.Substring(1).ToLowerInvariant() : "");
        }

        return UserActionPrefix + string.Join(" ", parts);
    }
}
