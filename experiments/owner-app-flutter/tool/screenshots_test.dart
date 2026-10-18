// Writes PNG screenshots of every screen and state to docs/screenshots/.
// Not part of `flutter test`: run it on purpose with
//
//   flutter test --update-goldens tool/screenshots_test.dart
//
// The test environment has no system fonts, so Roboto and the Material icon
// font are loaded from the Flutter SDK cache. The planned product face is
// Geist; these pictures show layout, colour and states, not final type.
import 'dart:io';

import 'package:avrana_owner_prototype/main.dart';
import 'package:avrana_owner_prototype/sim.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> loadFonts() async {
  final root = Platform.environment['FLUTTER_ROOT']!;
  final dir = '$root/bin/cache/artifacts/material_fonts';
  Future<ByteData> read(String name) async =>
      ByteData.sublistView(await File('$dir/$name').readAsBytes());
  final roboto = FontLoader('Roboto');
  for (final name in ['Roboto-Regular.ttf', 'Roboto-Medium.ttf', 'Roboto-Bold.ttf']) {
    roboto.addFont(read(name));
  }
  await roboto.load();
  final icons = FontLoader('MaterialIcons')
    ..addFont(read('MaterialIcons-Regular.otf'));
  await icons.load();
}

void main() {
  setUpAll(loadFonts);

  Future<Sim> start(WidgetTester tester, Size size) async {
    tester.view.physicalSize = size * 2;
    tester.view.devicePixelRatio = 2;
    addTearDown(tester.view.reset);
    final sim = Sim()..wait = Duration.zero;
    await tester.pumpWidget(OwnerPrototypeApp(sim: sim));
    return sim;
  }

  Future<void> go(WidgetTester tester, String place) async {
    await tester.tap(find.text(place).last);
    await tester.pumpAndSettle();
  }

  Future<void> shot(WidgetTester tester, String name) async {
    await tester.pumpAndSettle();
    await expectLater(find.byType(MaterialApp),
        matchesGoldenFile('../docs/screenshots/$name.png'));
  }

  const phone = Size(390, 844);

  testWidgets('phone screens and states', (tester) async {
    final sim = await start(tester, phone);
    await shot(tester, '01-setup-intro');
    await tester.tap(find.text('Find my box'));
    await shot(tester, '02-setup-found');
    await tester.tap(find.text('Avrana Party 7F3A'));
    await shot(tester, '03-setup-code');
    sim.setScenario(SetupScenario.permissionDenied);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Find my box'));
    await shot(tester, '04-setup-permission-denied');
    await go(tester, 'Dashboard');
    await shot(tester, '05-dashboard');
    sim.setReachable(false);
    await shot(tester, '06-dashboard-unreachable');
    sim.setReachable(true);
    await go(tester, 'Library');
    await shot(tester, '07-library');
    await tester.tap(find.text('Arcade'));
    await shot(tester, '08-library-empty');
    await tester.tap(find.text('Show all games'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Hello Party'));
    await shot(tester, '09-game-update-failed');
    await tester.pageBack();
    await tester.pumpAndSettle();
    await go(tester, 'Party');
    await shot(tester, '10-party');
    await tester.tap(find.text('End game for everyone'));
    await shot(tester, '11-party-confirm');
    await tester.tap(find.text('Cancel'));
    sim.setPartyActive(false);
    await shot(tester, '12-party-empty');
  });

  testWidgets('tablet width uses the rail', (tester) async {
    await start(tester, const Size(900, 700));
    await go(tester, 'Dashboard');
    await shot(tester, '13-dashboard-wide');
  });
}
