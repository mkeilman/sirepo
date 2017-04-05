'use strict';

var srlog = SIREPO.srlog;
var srdbg = SIREPO.srdbg;

SIREPO.appLocalRoutes.lattice = '/lattice/:simulationId';
SIREPO.appLocalRoutes.visualization = '/visualization/:simulationId';
SIREPO.PLOTTING_SUMMED_LINEOUTS = true;

SIREPO.app.config(function($routeProvider, localRoutesProvider) {
    if (SIREPO.IS_LOGGED_OUT) {
        return;
    }
    var localRoutes = localRoutesProvider.$get();
    $routeProvider
        .when(localRoutes.source, {
            controller: 'HellwegSourceController as source',
            templateUrl: '/static/html/hellweg-source.html' + SIREPO.SOURCE_CACHE_KEY,
        })
        .when(localRoutes.lattice, {
            controller: 'HellwegLatticeController as lattice',
            templateUrl: '/static/html/hellweg-lattice.html' + SIREPO.SOURCE_CACHE_KEY,
        })
        .when(localRoutes.visualization, {
            controller: 'HellwegVisualizationController as visualization',
            templateUrl: '/static/html/hellweg-visualization.html' + SIREPO.SOURCE_CACHE_KEY,
        });
});

SIREPO.app.controller('HellwegLatticeController', function (appState, panelState, $scope) {
    var self = this;
    self.appState = appState;
    self.toolbarItems = ['powerElement', 'cellElement', 'cellsElement', 'driftElement', 'saveElement'];

    function isElementModelName(modelName) {
        return modelName.indexOf('Element') >= 0;
    }

    function itemIndex(item) {
        var beamline = appState.models.beamline;
        for (var i = 0; i < beamline.length; i++) {
            if (beamline[i].id == item.id) {
                return i;
            }
        }
        return -1;
    }

    function newItem(modelName) {
        return appState.setModelDefaults({
            type: modelName,
        }, modelName);
    }

    function updateSaveElementFields() {
        var m = appState.models.saveElement;
        if (m) {
            panelState.showField('saveElement', 'particleLimit', m.particleRange == 'count');
            ['particleStart', 'particleEnd'].forEach(function(f) {
                panelState.showField('saveElement', f, m.particleRange == 'range');
            });
        }
    }

    self.deleteItem = function(item) {
        if (! item) {
            return;
        }
        self.selectItem(item);
        $('#hellweg-delete-element-confirmation').modal('show');
    };

    self.deleteSelected = function() {
        if (self.selectedItem) {
            var index = itemIndex(self.selectedItem);
            if (index >= 0) {
                self.selectedItem = null;
                appState.models.beamline.splice(index, 1);
                appState.saveChanges('beamline');
            }
        }
    };

    self.dropItem = function(index, item) {
        if (! item) {
            return;
        }
        if (angular.isObject(item)) {
            var beamline = appState.models.beamline;
            var i = itemIndex(item);
            if (index == i) {
                return;
            }
            item = beamline.splice(i, 1)[0];
            if (i < index) {
                index--;
            }
            beamline.splice(index, 0, item);
            appState.saveChanges('beamline');
            self.selectItem(item);
        }
        else {
            self.selectedIndex = index;
            self.editItem(newItem(item));
        }
    };

    self.dropLast = function(item) {
        self.dropItem(appState.models.beamline.length, item);
    };

    self.editItem = function(item) {
        appState.models[item.type] = item;
        panelState.showModalEditor(item.type);
    };

    self.handleModalShown = function(name) {
        if (name == 'saveElement') {
            updateSaveElementFields();
        }
    };

    self.isSelected = function(item) {
        if (self.selectedItem) {
            return item.id == self.selectedItem.id;
        }
        return false;
    };

    self.itemName = function(item) {
        var modelName = angular.isObject(item) ? item.type : item;
        if (modelName) {
            return appState.viewInfo(modelName).title;
        }
        return '';
    };

    self.itemValues = function(item) {
        return appState.viewInfo(item.type).advanced.map(function(f) {
            return item[f];
        }).join(' ');
    };

    self.selectItem = function(item) {
        self.selectedItem = angular.isObject(item) ? item : null;
    };

    self.selectedItemName = function() {
        if (self.selectedItem) {
            return self.itemName(self.selectedItem) + ' ' + self.itemValues(self.selectedItem);
        }
        return '';
    };

    $scope.$on('cancelChanges', function(e, name) {
        if (isElementModelName(name)) {
            appState.removeModel(name);
            appState.cancelChanges('beamline');
        }
    });

    $scope.$on('modelChanged', function(e, name) {
        if (isElementModelName(name)) {
            if (! appState.models[name].id) {
                appState.models[name].id = appState.maxId(appState.models.beamline) + 1;
                appState.models.beamline.splice(self.selectedIndex, 0, appState.models[name]);
                self.selectedItem = appState.models[name];
            }
            appState.removeModel(name);
            appState.saveChanges('beamline');
        }
    });

    appState.watchModelFields($scope, ['saveElement.particleRange'], updateSaveElementFields);
});

SIREPO.app.controller('HellwegSourceController', function (appState, panelState, $scope) {
    var self = this;

    function isActiveField(model, field) {
        var fieldClass = '.model-' + model + '-' + field;
        return $(fieldClass).find('input').is(':focus');
    }

    function updateAllFields() {
        updateBeamFields();
        updateSolenoidFields();
    }

    function updateBeamFields() {
        var beam = appState.models.beam;
        if (beam.transversalDistribution == 'sph2d') {
            updateCurvature();
        }
        panelState.showField('beam', 'spaceChargeCore', beam.spaceCharge == 'coulomb' || beam.spaceCharge == 'elliptic');
        panelState.showTab('beam', 2, beam.transversalDistribution == 'twiss4d');
        panelState.showTab('beam', 3, beam.transversalDistribution == 'sph2d');
        panelState.showTab('beam', 4, beam.transversalDistribution == 'ell2d');
        ['energyDeviation', 'phaseDeviation'].forEach(function(f) {
            panelState.showField('energyPhaseDistribution', f, beam.longitudinalDistribution == 'norm2d' && appState.models.energyPhaseDistribution.distributionType == 'gaussian');
        });
    }

    function updateCurvature() {
        var dist = appState.models.sphericalDistribution;
        if (isActiveField('sphericalDistribution', 'curvatureFactor')) {
            if (dist.curvatureFactor !== undefined) {
                dist.curvature = dist.curvatureFactor > 0
                    ? 'concave'
                    : (dist.curvatureFactor < 0
                       ? 'convex'
                       : 'flat');
            }
        }
        else {
            if (dist.curvature == 'concave') {
                if (dist.curvatureFactor === 0) {
                    dist.curvatureFactor = 1;
                }
                else {
                    dist.curvatureFactor = Math.abs(dist.curvatureFactor);
                }
            }
            else if (dist.curvature == 'convex') {
                if (dist.curvatureFactor === 0) {
                    dist.curvatureFactor = -1;
                }
                else {
                    dist.curvatureFactor = - Math.abs(dist.curvatureFactor);
                }
            }
            else {
                dist.curvatureFactor = 0;
            }
        }
    }

    function updateSolenoidFields() {
        var solenoid = appState.models.solenoid;
        ['fieldStrength', 'length', 'z0', 'fringeRegion'].forEach(function(f) {
            panelState.showField('solenoid', f, solenoid.sourceDefinition == 'values');
        });
    }

    self.handleModalShown = function(name) {
        updateAllFields();
    };

    appState.watchModelFields($scope, ['beam.transversalDistribution', 'beam.spaceCharge', 'sphericalDistribution.curvature', 'sphericalDistribution.curvatureFactor', 'energyPhaseDistribution.distributionType'], updateBeamFields);
    appState.watchModelFields($scope, ['solenoid.sourceDefinition'], updateSolenoidFields);
    appState.whenModelsLoaded($scope, updateAllFields);
});

SIREPO.app.controller('HellwegVisualizationController', function (appState, frameCache, persistentSimulation, $scope, $rootScope) {
    var self = this;
    self.model = 'animation';
    self.settingsModel = 'simulationSettings';
    self.simulationErrors = '';

    self.handleStatus = function(data) {
        self.simulationErrors = data.errors || '';
        frameCache.setFrameCount(data.frameCount);
        if (data.startTime) {
            appState.models.beamAnimation.startTime = data.startTime;
            appState.saveQuietly('beamAnimation');
            appState.models.beamHistogramAnimation.startTime = data.startTime;
            appState.saveQuietly('beamHistogramAnimation');
            $rootScope.$broadcast('animation.summaryData', data.summaryData);
        }
    };

    self.getFrameCount = function() {
        return frameCache.getFrameCount();
    };

    persistentSimulation.initProperties(self);
    frameCache.setAnimationArgs({
        beamAnimation: ['reportType', 'histogramBins', 'startTime'],
        beamHistogramAnimation: ['reportType', 'histogramBins', 'startTime'],
    });
    self.persistentSimulationInit($scope);
});

SIREPO.app.directive('appHeader', function(appState, panelState) {
    return {
        restirct: 'A',
        scope: {
            nav: '=appHeader',
        },
        template: [
            '<div class="navbar-header">',
              '<a class="navbar-brand" href="/#about"><img style="width: 40px; margin-top: -10px;" src="/static/img/radtrack.gif" alt="radiasoft"></a>',
              '<div class="navbar-brand"><a href data-ng-click="nav.openSection(\'simulations\')">Hellweg</a></div>',
            '</div>',
            '<div data-app-header-left="nav"></div>',
            '<ul class="nav navbar-nav navbar-right" data-login-menu=""></ul>',
            '<ul class="nav navbar-nav navbar-right" data-ng-show="isLoaded()">',
              '<li data-ng-class="{active: nav.isActive(\'source\')}"><a href data-ng-click="nav.openSection(\'source\')"><span class="glyphicon glyphicon-flash"></span> Source</a></li>',
              '<li data-ng-class="{active: nav.isActive(\'lattice\')}"><a href data-ng-click="nav.openSection(\'lattice\')"><span class="glyphicon glyphicon-option-horizontal"></span> Lattice</a></li>',
              '<li data-ng-class="{active: nav.isActive(\'visualization\')}"><a href data-ng-click="nav.openSection(\'visualization\')"><span class="glyphicon glyphicon-picture"></span> Visualization</a></li>',
            '</ul>',
            '<ul class="nav navbar-nav navbar-right" data-ng-show="nav.isActive(\'simulations\')">',
              '<li><a href data-ng-click="showSimulationModal()"><span class="glyphicon glyphicon-plus sr-small-icon"></span><span class="glyphicon glyphicon-file"></span> New Simulation</a></li>',
              '<li><a href data-ng-click="showNewFolderModal()"><span class="glyphicon glyphicon-plus sr-small-icon"></span><span class="glyphicon glyphicon-folder-close"></span> New Folder</a></li>',
            '</ul>',
        ].join(''),
        controller: function($scope) {
            $scope.hasLattice = function() {
                return appState.isLoaded();
            };
            $scope.isLoaded = function() {
                if ($scope.nav.isActive('simulations'))
                    return false;
                return appState.isLoaded();
            };
            $scope.showNewFolderModal = function() {
                panelState.showModalEditor('simulationFolder');
            };
            $scope.showSimulationModal = function() {
                panelState.showModalEditor('simulation');
            };
        },
    };
});

SIREPO.app.directive('summaryTable', function(appState, panelState, $interval) {
    return {
        restirct: 'A',
        scope: {
            modelName: '@summaryTable',
        },
        template: [
            '<div class="col-sm-12">',
              '<div class="lead" data-ng-if="summaryRows">Results</div>',
                '<table>',
                '<tr data-ng-repeat="item in summaryRows">',
                  '<td data-ng-if="item.length == 1"><br /><strong>{{ item[0] }}</strong></td>',
                  '<td data-ng-if="item.length > 1">{{ item[0] }}:</td>',
                  '<td>&nbsp;</td>',
                  '<td>{{ item[1] }}</td>',
                '</tr>',
              '</table>',
            '</div>',
        ].join(''),
        controller: function($scope) {
            function parseSummaryRows(summaryText) {
                var text = summaryText.replace(/^(\n|.)*RESULTS\n+==+/, '').replace(/==+/, '');
                var label = null;
                $scope.summaryRows = [];
                text.split(/\n+/).forEach(function(line) {
                    line.split(/\s*=\s*/).forEach(function(v) {
                        if (label) {
                            $scope.summaryRows.push([label, v]);
                            label = null;
                        }
                        else if (v.indexOf(':') >= 0) {
                            $scope.summaryRows.push([v]);
                        }
                        else {
                            label = v;
                        }
                    });
                });
            }

            function updateSummaryInfo(e, summaryText) {
                if (summaryText) {
                    parseSummaryRows(summaryText);
                }
                else {
                    $scope.summaryRows = null;
                }
            }
            $scope.$on($scope.modelName + '.summaryData', updateSummaryInfo);
        }
    };
});