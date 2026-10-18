import 'package:flutter/material.dart';

import 'theme.dart';

/// A word beside anything that only pretends: scanning, joining Wi-Fi,
/// restarting the box. Text, never colour alone.
class SimulatedTag extends StatelessWidget {
  const SimulatedTag({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Simulated in this prototype',
      child: ExcludeSemantics(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(
            border: Border.all(color: AvranaColors.warn),
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text('Simulated',
              style: Theme.of(context)
                  .textTheme
                  .labelSmall
                  ?.copyWith(color: AvranaColors.warn)),
        ),
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.simulated = false});
  final String text;
  final bool simulated;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 24, bottom: 8),
      child: Wrap(
        spacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Semantics(
            header: true,
            child: Text(text,
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.w600)),
          ),
          if (simulated) const SimulatedTag(),
        ],
      ),
    );
  }
}

enum NoticeKind { info, warn, error }

/// Something to know now: an icon, a title, one sentence, at most one action.
class Notice extends StatelessWidget {
  const Notice({
    super.key,
    required this.title,
    required this.text,
    this.kind = NoticeKind.info,
    this.action,
    this.onAction,
  });
  final String title;
  final String text;
  final NoticeKind kind;
  final String? action;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final (icon, color) = switch (kind) {
      NoticeKind.info => (Icons.info_outline, AvranaColors.info),
      NoticeKind.warn => (Icons.warning_amber_rounded, AvranaColors.warn),
      NoticeKind.error => (Icons.error_outline, AvranaColors.error),
    };
    final theme = Theme.of(context);
    return Semantics(
      container: true,
      liveRegion: true,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
          child: Wrap(
            alignment: WrapAlignment.end,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 8,
            runSpacing: 8,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 2, right: 12),
                    child: Icon(icon, color: color),
                  ),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(title,
                            style: theme.textTheme.bodyLarge
                                ?.copyWith(fontWeight: FontWeight.w600)),
                        Text(text,
                            style: theme.textTheme.bodyMedium?.copyWith(
                                color: theme.colorScheme.onSurfaceVariant)),
                      ],
                    ),
                  ),
                ],
              ),
              if (action != null)
                OutlinedButton(onPressed: onAction, child: Text(action!)),
            ],
          ),
        ),
      ),
    );
  }
}

/// A status as an icon and a word.
class StatusWord extends StatelessWidget {
  const StatusWord(this.text, {super.key, this.color, this.icon});
  final String text;
  final Color? color;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final tone = color ?? Theme.of(context).colorScheme.onSurfaceVariant;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (icon != null) ...[
          Icon(icon, size: 16, color: tone),
          const SizedBox(width: 4),
        ],
        Flexible(
          child: Text(text,
              style:
                  Theme.of(context).textTheme.bodySmall?.copyWith(color: tone)),
        ),
      ],
    );
  }
}

/// The page body: one column, readable on a phone, centred when wide.
class PageBody extends StatelessWidget {
  const PageBody({super.key, required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          children: children,
        ),
      ),
    );
  }
}

Future<bool> confirm(BuildContext context,
    {required String title,
    required String text,
    required String action}) async {
  final answer = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: Text(text),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel')),
        FilledButton(
            onPressed: () => Navigator.pop(context, true), child: Text(action)),
      ],
    ),
  );
  return answer ?? false;
}

void say(BuildContext context, String text) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text)));
}
