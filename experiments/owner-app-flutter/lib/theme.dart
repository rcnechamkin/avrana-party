import 'package:flutter/material.dart';

/// The Avrana Party theme for Material 3 widgets.
///
/// Values are the Party theme of the Design Foundation
/// (docs/design/foundation/tokens.json). Material's colour roles are filled
/// by hand instead of from a seed, so nothing is tinted purple: the main
/// action is ink, and Atomic Purple marks selection and focus only.
abstract final class AvranaColors {
  static const surface = Color(0xFF0D0D0F);
  static const surfaceLow = Color(0xFF161618);
  static const surfaceRaised = Color(0xFF1E1E21);
  static const onSurface = Color(0xFFEDEAE4);
  static const onSurfaceMuted = Color(0xFFAEABA7);
  static const outlineQuiet = Color(0xFF232325); // white at 9% on the ground
  static const outlineControl = Color(0xFF6E6C72);
  static const ink = Color(0xFF121214);
  static const accent = Color(0xFFB9A9E8);
  static const selected = Color(0x29B9A9E8); // accent at 16%
  static const materialSolid = Color(0xFF1C1A26);
  static const ok = Color(0xFF70C696);
  static const warn = Color(0xFFE6B862);
  static const error = Color(0xFFF08A7E);
  static const info = Color(0xFF81AFDF);
}

ThemeData avranaTheme() {
  const scheme = ColorScheme(
    brightness: Brightness.dark,
    primary: AvranaColors.onSurface,
    onPrimary: AvranaColors.ink,
    secondary: AvranaColors.accent,
    onSecondary: AvranaColors.ink,
    secondaryContainer: AvranaColors.selected,
    onSecondaryContainer: AvranaColors.onSurface,
    tertiary: AvranaColors.accent,
    onTertiary: AvranaColors.ink,
    error: AvranaColors.error,
    onError: AvranaColors.ink,
    surface: AvranaColors.surface,
    onSurface: AvranaColors.onSurface,
    onSurfaceVariant: AvranaColors.onSurfaceMuted,
    surfaceContainerLowest: AvranaColors.surface,
    surfaceContainerLow: AvranaColors.surfaceLow,
    surfaceContainer: AvranaColors.surfaceLow,
    surfaceContainerHigh: AvranaColors.surfaceRaised,
    surfaceContainerHighest: AvranaColors.surfaceRaised,
    outline: AvranaColors.outlineControl,
    outlineVariant: AvranaColors.outlineQuiet,
    surfaceTint: Colors.transparent,
    scrim: Color(0x99040406),
  );
  const radius = BorderRadius.all(Radius.circular(10));
  const shape = RoundedRectangleBorder(borderRadius: radius);
  final base = ThemeData(
    useMaterial3: true,
    // Bundled so the web build asks no font server for anything. The product
    // face is Geist; no TTF of it is in the repository yet.
    fontFamily: 'Roboto',
    colorScheme: scheme,
    scaffoldBackgroundColor: scheme.surface,
    materialTapTargetSize: MaterialTapTargetSize.padded,
    visualDensity: VisualDensity.standard,
  );
  return base.copyWith(
    appBarTheme: AppBarTheme(
      backgroundColor: scheme.surface,
      scrolledUnderElevation: 0,
      titleTextStyle: base.textTheme.titleLarge
          ?.copyWith(color: scheme.onSurface, fontWeight: FontWeight.w600),
    ),
    cardTheme: const CardThemeData(
      elevation: 0,
      margin: EdgeInsets.zero,
      color: AvranaColors.surfaceLow,
      shape: RoundedRectangleBorder(
        borderRadius: radius,
        side: BorderSide(color: AvranaColors.outlineQuiet),
      ),
    ),
    dividerTheme:
        const DividerThemeData(color: AvranaColors.outlineQuiet, space: 1),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
          minimumSize: const Size(48, 48), shape: shape),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(48, 48),
        shape: shape,
        foregroundColor: scheme.onSurface,
        side: const BorderSide(color: AvranaColors.outlineControl),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        minimumSize: const Size(48, 48),
        shape: shape,
        foregroundColor: scheme.onSurface,
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: AvranaColors.materialSolid,
      indicatorColor: AvranaColors.selected,
      elevation: 0,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => TextStyle(
          fontSize: 12,
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.w600
              : FontWeight.w500,
          color: states.contains(WidgetState.selected)
              ? scheme.onSurface
              : scheme.onSurfaceVariant,
        ),
      ),
    ),
    navigationRailTheme: const NavigationRailThemeData(
      backgroundColor: AvranaColors.materialSolid,
      indicatorColor: AvranaColors.selected,
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: AvranaColors.materialSolid,
      showDragHandle: true,
    ),
    dialogTheme: const DialogThemeData(
      backgroundColor: AvranaColors.materialSolid,
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(18))),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: AvranaColors.surfaceRaised,
      contentTextStyle: TextStyle(color: scheme.onSurface),
      shape: shape,
    ),
    chipTheme: base.chipTheme.copyWith(
      side: const BorderSide(color: AvranaColors.outlineControl),
      selectedColor: AvranaColors.selected,
      shape: shape,
    ),
    listTileTheme: const ListTileThemeData(
      iconColor: AvranaColors.onSurfaceMuted,
      minVerticalPadding: 12,
    ),
  );
}
