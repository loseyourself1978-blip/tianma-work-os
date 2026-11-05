#!/usr/bin/env python3
"""Generate a real native TWOS target, sharing the direct build's Swift sources.

No account, signing credential, provisioning request, or application is changed.
Store packaging remains gated on matching prepared resources and sandbox review.
"""
from pathlib import Path
import hashlib
import json
import plistlib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'packaging/macos/Xcode'
SOURCES = ['CodexAttachments.swift', 'CodexTelemetry.swift', 'NativeCodex.swift',
           'IntegratedWorkbench.swift', 'PairedWorkflow.swift', 'TianmaLauncher.swift']


def generate():
    objects = {}

    def obj(object_name, **value):
        key = hashlib.sha256(object_name.encode()).hexdigest()[:24].upper()
        objects[key] = value
        return key

    source_files = [obj('file-' + name, isa='PBXFileReference', lastKnownFileType='sourcecode.swift',
                       path='../' + name, sourceTree='<group>') for name in SOURCES]
    main = obj('generated-main', isa='PBXFileReference', lastKnownFileType='sourcecode.swift',
               name='Generated product entry point', path='$(DERIVED_FILE_DIR)/main.swift', sourceTree='<absolute>')
    product = obj('product', isa='PBXFileReference', explicitFileType='wrapper.application',
                  path='Tianma Work OS.app', sourceTree='BUILT_PRODUCTS_DIR', includeInIndex=0)
    source_group = obj('sources', isa='PBXGroup', name='Shared product sources', children=source_files + [main], sourceTree='<group>')
    products = obj('products', isa='PBXGroup', name='Products', children=[product], sourceTree='<group>')
    group = obj('group', isa='PBXGroup', children=[source_group, products], sourceTree='<group>')
    prepare = obj('prepare-source', isa='PBXShellScriptBuildPhase', buildActionMask=2147483647,
                  name='Prepare shared Swift entry point', files=[], inputPaths=['$(SRCROOT)/../' + x for x in SOURCES],
                  outputPaths=['$(DERIVED_FILE_DIR)/main.swift'], runOnlyForDeploymentPostprocessing=0,
                  shellPath='/bin/sh', shellScript='set -eu\nmkdir -p "$DERIVED_FILE_DIR"\n' +
                  'cat ' + ' '.join('"$SRCROOT/../' + x + '"' for x in SOURCES) + ' > "$DERIVED_FILE_DIR/main.swift"\n')
    source_build = obj('compile-main', isa='PBXBuildFile', fileRef=main)
    compile_phase = obj('compile', isa='PBXSourcesBuildPhase', buildActionMask=2147483647,
                        files=[source_build], runOnlyForDeploymentPostprocessing=0)
    resources = obj('resources', isa='PBXShellScriptBuildPhase', buildActionMask=2147483647,
                    name='Verify and stage matching product resources', files=[], inputPaths=[], outputPaths=[],
                    alwaysOutOfDate=1, runOnlyForDeploymentPostprocessing=0, shellPath='/bin/sh',
                    shellScript='set -eu\n/usr/bin/python3 "$SRCROOT/../../../scripts/stage_xcode_resources.py"\n')
    framework_phase = obj('frameworks', isa='PBXFrameworksBuildPhase', buildActionMask=2147483647,
                          files=[], runOnlyForDeploymentPostprocessing=0)
    configs = []
    for name, store in [('Debug', False), ('Store', True)]:
        settings = dict(PRODUCT_NAME='Tianma Work OS', PRODUCT_BUNDLE_IDENTIFIER='com.tianma.workos',
                        DEVELOPMENT_TEAM='BZJWQJ352K', CODE_SIGN_STYLE='Automatic',
                        CODE_SIGN_IDENTITY='Apple Distribution' if store else 'Apple Development',
                        CODE_SIGN_ENTITLEMENTS='TWOS.sandbox.entitlements', ENABLE_APP_SANDBOX='YES',
                        ENABLE_HARDENED_RUNTIME='YES', ENABLE_USER_SCRIPT_SANDBOXING='NO',
                        SWIFT_VERSION='5.0', SWIFT_OPTIMIZATION_LEVEL='-O' if store else '-Onone',
                        MACOSX_DEPLOYMENT_TARGET='14.0', SDKROOT='macosx', SUPPORTED_PLATFORMS='macosx',
                        ARCHS='arm64', ONLY_ACTIVE_ARCH='YES', GENERATE_INFOPLIST_FILE='NO',
                        INFOPLIST_FILE='Info.plist', SKIP_INSTALL='NO', INSTALL_PATH='$(LOCAL_APPS_DIR)',
                        OTHER_LDFLAGS=['$(inherited)', '-framework', 'AppKit', '-framework', 'WebKit', '-framework', 'LocalAuthentication'],
                        TWOS_PREPARED_APP='', TWOS_STORE_READINESS='',
                        TWOS_DISTRIBUTION='store' if store else 'sandbox-engineering')
        configs.append(obj('target-config-' + name, isa='XCBuildConfiguration', name=name, buildSettings=settings))
    config_list = obj('target-configs', isa='XCConfigurationList', buildConfigurations=configs,
                      defaultConfigurationIsVisible=0, defaultConfigurationName='Debug')
    target = obj('target', isa='PBXNativeTarget', name='TWOS', productName='Tianma Work OS',
                 productType='com.apple.product-type.application', productReference=product,
                 buildConfigurationList=config_list, buildPhases=[prepare, compile_phase, framework_phase, resources],
                 buildRules=[], dependencies=[])
    project_configs = [obj('project-config-' + name, isa='XCBuildConfiguration', name=name, buildSettings={}) for name in ('Debug', 'Store')]
    pcl = obj('project-configs', isa='XCConfigurationList', buildConfigurations=project_configs,
              defaultConfigurationIsVisible=0, defaultConfigurationName='Debug')
    project = obj('project', isa='PBXProject', attributes={'LastUpgradeCheck': '2700', 'TargetAttributes': {target: {'DevelopmentTeam': 'BZJWQJ352K', 'ProvisioningStyle': 'Automatic'}}},
                  buildConfigurationList=pcl, compatibilityVersion='Xcode 14.0', developmentRegion='en',
                  hasScannedForEncodings=0, knownRegions=['en', 'zh-Hans', 'Base'], mainGroup=group,
                  productRefGroup=products, projectDirPath='', projectRoot='', targets=[target])
    directory = DEST / 'TWOS.xcodeproj'
    directory.mkdir(parents=True, exist_ok=True)
    # Xcode accepts the standard XML property-list serialization of PBX objects.
    (directory / 'project.pbxproj').write_bytes(plistlib.dumps(dict(archiveVersion='1', classes={}, objectVersion='56', objects=objects, rootObject=project), sort_keys=False))
    for name, config in [('TWOS Sandbox Engineering', 'Debug'), ('TWOS Mac App Store', 'Store')]:
        scheme = ET.Element('Scheme', LastUpgradeVersion='2700', version='1.3')
        build = ET.SubElement(scheme, 'BuildAction', parallelizeBuildables='NO', buildImplicitDependencies='YES')
        entries = ET.SubElement(build, 'BuildActionEntries')
        entry = ET.SubElement(entries, 'BuildActionEntry', buildForTesting='YES', buildForRunning='YES', buildForProfiling='YES', buildForArchiving='YES', buildForAnalyzing='YES')
        reference = dict(BuildableIdentifier='primary', BlueprintIdentifier=target, BuildableName='Tianma Work OS.app', BlueprintName='TWOS', ReferencedContainer='container:TWOS.xcodeproj')
        ET.SubElement(entry, 'BuildableReference', **reference)
        launch = ET.SubElement(scheme, 'LaunchAction', buildConfiguration=config, selectedDebuggerIdentifier='Xcode.DebuggerFoundation.Debugger.LLDB', selectedLauncherIdentifier='Xcode.IDEFoundation.Launcher.LLDB', launchStyle='0', useCustomWorkingDirectory='NO', ignoresPersistentStateOnLaunch='NO', debugDocumentVersioning='YES', allowLocationSimulation='NO')
        runnable = ET.SubElement(launch, 'BuildableProductRunnable', runnableDebuggingMode='0')
        ET.SubElement(runnable, 'BuildableReference', **reference)
        ET.SubElement(scheme, 'AnalyzeAction', buildConfiguration=config)
        ET.SubElement(scheme, 'ArchiveAction', buildConfiguration=config, revealArchiveInOrganizer='YES')
        path = directory / 'xcshareddata/xcschemes' / (name + '.xcscheme')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(ET.tostring(scheme, encoding='utf-8', xml_declaration=True))
    return directory


if __name__ == '__main__':
    print(generate())
