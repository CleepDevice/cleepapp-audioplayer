/**
 * Audioplayer config component
 * Handle audioplayer application configuration
 * If your application doesn't need configuration page, delete this file and its references into desc.json
 */
angular
.module('Cleep')
.directive('audioplayerConfigComponent', ['$rootScope', 'cleepService', 'toastService', 'audioplayerService', '$mdDialog',
function($rootScope, cleepService, toastService, audioplayerService, $mdDialog) {

    var audioplayerConfigController = function($scope) {
        var self = this;
        self.audioplayerService = audioplayerService;
        self.formats = [
            { label: 'mp3', value: 'audio/mpeg' },
            { label: 'aac', value: 'audio/aac' },
            { label: 'ogg', value: 'audio/ogg' },
            { label: 'flac', value: 'audio/flac' },
        ];
        self.selectedFormat = 'audio/mpeg';
        self.url = '';
        self.trackIndex = 0;
        self.selectedPlayerId = undefined;
        self.volume = 100;
        self.repeat = false;
        self.playerIndex = null;
        self.players = [];

        self.$onInit = function() {
            audioplayerService.refreshPlayers();
            self.playerControls = [
                { icon: 'skip-previous', tooltip: 'Play previous track', click: self.previous },
                { icon: 'play-pause', tooltip: 'Toggle play/pause', click: self.pause },
                { icon: 'stop', tooltip: 'Stop playback', click: self.stop },
                { icon: 'skip-next', tooltip: 'Play next track', click: self.next },
            ];
        };

        self.play = function() {
            console.log('play', {item});
            audioplayerService.play(self.url, self.selectedFormat);
        };

        self.pause = function(item) {
            console.log('pause', {item});
            audioplayerService.pause(item.playerId);
        };

        self.stop = function(item) {
            audioplayerService.stop(item.playerId);
            self.cancelDialog();
        };

        self.next = function(playerId) {
            audioplayerService.next(playerId);
        };

        self.previous = function(playerId) {
            audioplayerService.previous(playerId);
        };

        self.setVolume = function(playerId) {
            audioplayerService.setVolume(playerId, self.volume);
        };

        self.setRepeat = function(playerId) {
            audioplayerService.setRepeat(playerId, self.repeat);
        };

        self.shufflePlaylist = function(playerId) {
            audioplayerService.shufflePlaylist(playerId)
                .then((response) => {
                    if (response.error) {
                        return;
                    }
                    self.loadPlaylist(self.selectedPlayerId);
                });
        };

        self.addTrack = function(playerId) {
            audioplayerService.addTrack(self.selectedPlayerId, self.url, self.selectedFormat, self.trackIndex)
                .then((response) => {
                    if (response.error) {
                        return;
                    }
                    self.loadPlaylist(self.selectedPlayerId);
                });
        };

        self.removeTrack = function(playerId, trackIndex) {
            audioplayerService.removeTrack(playerId, trackIndex)
                .then((response) => {
                    if (response.error) {
                        return;
                    }
                    self.loadPlaylist(self.selectedPlayerId);
                });
        };

        self.loadPlaylist = function(playerId) {
            return audioplayerService.getPlaylist(playerId)
                .then((response) => {
                    self.selectedPlayerId = playerId;
                    self.repeat = response.data.repeat;
                    self.volume = response.data.volume;
                });
        };

        self.showPlaylist = function(item, index) {
            self.loadPlaylist(item.playerId).then(() => {
                self.playerIndex = index;
                self.openDialog();
            });
        };

        self.openDialog = function() {
            return $mdDialog.show({
                controller: function() { return self; },
                controllerAs: '$ctrl',
                templateUrl: 'player.dialog.html',
                parent: angular.element(document.body),
                clickOutsideToClose: false,
                fullscreen: true,
            });
        };

        self.cancelDialog = function() {
            $mdDialog.cancel();
        };

        $scope.$watchCollection(
            () => audioplayerService.playlist,
            (playlist) => {
                if (!Object.keys(audioplayerService.playlist).length) {
                    $mdDialog.cancel();
                }
            }
        );

    	self.parsePlayers = function(rawPlayers) {
        	self.players.splice(0, self.players.length);
    	    for (const player of rawPlayers) {
        	    const title = player.metadata?.title ?? player.track.resource;
            	const subtitle = player.metadata?.title ? player.metadata.artist || 'no artist' + ' - ' + player.metadata.album || 'no album' : player.track.audio_format;

	            self.players.push({
    	            title,
        	        subtitle,
            	    playerId: player.playeruuid,
                	clicks: [
	                    { tooltip: 'Toggle play/pause', icon: 'play-pause', click: self.pause },
    	                { tooltip: 'Stop playback', icon: 'stop', click: self.stop },
        	            { tooltip: 'Show player', icon: 'music-circle', click: self.showPlaylist },
	                ],  
    	        }); 
        	}   
    	};

        $scope.$watchCollection(
            () => audioplayerService.players,
            (players) => {
				self.parsePlayers(players);
            }
        );
    };

    return {
        templateUrl: 'audioplayer.config.html',
        replace: true,
        scope: true,
        controller: audioplayerConfigController,
        controllerAs: '$ctrl',
    };
}]);
